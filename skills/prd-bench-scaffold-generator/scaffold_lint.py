#!/usr/bin/env python3
"""
scaffold_lint.py — Validates that SCAFFOLD.yaml + §1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml)
+ §1.9 (SCAFFOLD_CORNER_DESIGN.yaml) form a self-consistent design package.

Six fatal checks. (a)–(e) run per call in §1.8/§1.9 setup_api_calls / trigger
chains against the §1.5 endpoint table. (f) is a scaffold-level integrity check
over §1.1 entities ↔ §1.5 endpoints.

  (a) endpoint declared — (method, path-template) matches a §1.5 entry
  (b) role allowed      — call's `as:` value is in endpoint.roles
  (c) payload shape     — payload keys are a subset of endpoint.input (with `?`
                           optionals); every required input field is present
  (d) capture resolution — every `$.data.<field>` in `captures:` resolves to a
                           field declared on the endpoint's output entity in §1.1
                           (error-envelope fields `$.data.error_id` and
                           `$.data.message` are always valid per §1.0)
  (e) OCC version is dynamic — every payload field matching `expected_*_version`
                           is a `${var}` placeholder (or expression containing
                           one), never a hardcoded integer / numeric string.
                           Cascades silently bump parent.version between create
                           and the OCC call, so literals go stale — see SKILL.md
                           §1.8 per-instance contract item 3c.
  (f) FK reverse-reachability — every entity field declared with a description
                           matching `^FK -> <Parent>.id` has at least one GET
                           endpoint in §1.5 that lets a client discover the
                           child(ren) given the parent's id. Either sub-resource
                           form (`GET /<parent-collection>/{id}/<child-segment>`
                           with `output: <Child>` or `<Child>[]`) or filtered
                           list form (`GET /<child-collection>` with the FK
                           field declared as `<fk_field>?` in `input:`). See
                           SKILL.md §1.5 FK reverse-reachability principle.

Usage:
  scaffold_lint.py <task_dir>
      auto-detects SCAFFOLD.yaml / SCAFFOLD_DIFFICULTY_DESIGN.yaml /
      SCAFFOLD_CORNER_DESIGN.yaml under <task_dir>.

  scaffold_lint.py SCAFFOLD.yaml SCAFFOLD_DIFFICULTY_DESIGN.yaml \\
                   SCAFFOLD_CORNER_DESIGN.yaml
      explicit file list.

Flags:
  --json        emit JSON instead of human-readable text
  --warn-only   exit 0 even if violations found

Exit codes:
  0  clean lint (or --warn-only)
  1  violations present
  2  script error (missing file, parse error, missing PyYAML)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required (`pip install pyyaml`)", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Path & call parsing
# ---------------------------------------------------------------------------

_CALL_RE = re.compile(r"^\s*(GET|POST|PUT|PATCH|DELETE)\s+(\S+)\s*$")
_TEMPLATE_SEG_RE = re.compile(r"^\{[^/{}]+\}$")
_PLACEHOLDER_SEG_RE = re.compile(r"^(?:\$\{[^/{}]+\}|\{[^/{}]+\})$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def parse_call(s: str | None) -> tuple[str, str] | None:
    if not s:
        return None
    m = _CALL_RE.match(s)
    if not m:
        return None
    raw = m.group(2)
    # Strip query string and fragment — endpoint table matches on the path only.
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    path = raw.rstrip("/") or "/"
    return m.group(1), path


def _seg_is_dynamic(seg: str) -> bool:
    return bool(_PLACEHOLDER_SEG_RE.match(seg) or _UUID_RE.match(seg))


def path_matches_template(call_path: str, template: str) -> bool:
    """Structural match of a call path against a §1.5 template.

    Template uses {id}-style placeholders. Call may use ${var}, {var}, a
    hardcoded UUID, or a literal segment. Dynamic call segments match any
    template placeholder; literal segments must equal the template segment.
    """
    c_segs = (call_path or "").rstrip("/").split("/")
    t_segs = (template or "").rstrip("/").split("/")
    if len(c_segs) != len(t_segs):
        return False
    for cs, ts in zip(c_segs, t_segs):
        if _TEMPLATE_SEG_RE.match(ts):
            continue
        if _seg_is_dynamic(cs):
            return False
        if cs != ts:
            return False
    return True


# ---------------------------------------------------------------------------
# §1.5 endpoint table
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Endpoint:
    method: str
    path_template: str
    roles: set[str]
    required_inputs: set[str]
    optional_inputs: set[str]
    output_entity: str | None
    output_is_list: bool
    output_inline_fields: set[str] | None  # for `output: { k: type, ... }` form


def _split_input(raw: list | None) -> tuple[set[str], set[str]]:
    req: set[str] = set()
    opt: set[str] = set()
    for f in (raw or []):
        if not isinstance(f, str):
            continue
        f = f.strip()
        if not f:
            continue
        if f.endswith("?"):
            opt.add(f[:-1].strip())
        else:
            req.add(f)
    return req, opt


_INLINE_DICT_FIELD_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:")


def _try_string_inline_schema(s: str) -> set[str] | None:
    """Recover field names from a string that looks like an inline dict schema,
    e.g. `"{ renewed_count: integer, renewed_application_ids: string[] }"` —
    common when authors quote the output value because `string[]` is invalid
    inside YAML flow mappings."""
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    inner = s[1:-1]
    fields = set(_INLINE_DICT_FIELD_RE.findall(inner))
    return fields or None


def _parse_output(raw: Any) -> tuple[str | None, bool, set[str] | None]:
    """Returns (entity_name, is_list, inline_fields).

    - entity_name set + inline_fields None: standard entity reference.
    - entity_name None + inline_fields set: inline dict schema {k: type, ...},
      either as a real YAML dict or a quoted-string that looks like one.
    - both None: null / unknown / unparseable.
    """
    if raw is None:
        return None, False, None
    if isinstance(raw, dict):
        return None, False, {str(k).strip() for k in raw.keys() if str(k).strip()}
    s = str(raw).strip()
    if s in ("", "null", "None"):
        return None, False, None
    inline = _try_string_inline_schema(s)
    if inline is not None:
        return None, False, inline
    is_list = s.endswith("[]")
    if is_list:
        s = s[:-2].strip()
    return s, is_list, None


def load_endpoints(scaffold: dict) -> list[Endpoint]:
    out: list[Endpoint] = []
    for ep in scaffold.get("endpoints", []) or []:
        if not isinstance(ep, dict):
            continue
        method = str(ep.get("method", "")).upper().strip()
        path = str(ep.get("path", "")).strip()
        if not method or not path:
            continue
        req, opt = _split_input(ep.get("input"))
        entity, is_list, inline_fields = _parse_output(ep.get("output"))
        roles = {str(r).strip() for r in (ep.get("roles") or []) if str(r).strip()}
        out.append(
            Endpoint(
                method=method,
                path_template=path.rstrip("/") or "/",
                roles=roles,
                required_inputs=req,
                optional_inputs=opt,
                output_entity=entity,
                output_is_list=is_list,
                output_inline_fields=inline_fields,
            )
        )
    return out


def find_endpoint(method: str, path: str, endpoints: list[Endpoint]) -> Endpoint | None:
    matches = [
        e
        for e in endpoints
        if e.method == method and path_matches_template(path, e.path_template)
    ]
    if not matches:
        return None
    # Most specific (fewest {var} segments) wins.
    matches.sort(
        key=lambda e: sum(
            1 for s in e.path_template.split("/") if _TEMPLATE_SEG_RE.match(s)
        )
    )
    return matches[0]


# ---------------------------------------------------------------------------
# §1.1 entity field schemas
# ---------------------------------------------------------------------------

# Server-stamped fields always present on entity reads per common_fields: true
# convention in SKILL.md examples.
_COMMON_ENTITY_FIELDS: set[str] = {"id", "created_at", "updated_at", "version"}
# Error envelope fields, always valid in captures regardless of endpoint.
_ERROR_ENVELOPE_FIELDS: set[str] = {"error_id", "message"}


def load_entity_fields(scaffold: dict) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for ent in scaffold.get("entities", []) or []:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name", "")).strip()
        if not name:
            continue
        fields: set[str] = set()
        for f in ent.get("fields", []) or []:
            if isinstance(f, dict):
                fname = f.get("name") or f.get("field")
                if fname:
                    fields.add(str(fname).strip())
            elif isinstance(f, str):
                fname = f.split(":", 1)[0].strip()
                if fname:
                    fields.add(fname)
        fields |= _COMMON_ENTITY_FIELDS
        out[name] = fields
    return out


# ---------------------------------------------------------------------------
# Capture JSONPath validation
# ---------------------------------------------------------------------------

_CAPTURE_FIELD_RE = re.compile(r"^\$\.data\.([A-Za-z_][A-Za-z0-9_]*)$")
_CAPTURE_LIST_RE = re.compile(
    r"^\$\.data(?:\[\d+\]|\.\d+)\.([A-Za-z_][A-Za-z0-9_]*)$"
)
_NEGATIVE_TRIGGER_JSONPATHS = {"$.data.error_id", "$.data.message"}

# OCC version fields in payload MUST be `${var}` (or expression containing one),
# never a literal — see SKILL.md §1.8 per-instance contract item 3c. The key
# pattern matches `expected_<parent>_version` for any parent name declared in
# §1.7's concurrency_rules; the value pattern requires at least one `${...}`
# placeholder reference somewhere in the value.
_OCC_VERSION_KEY_RE = re.compile(r"^expected_.+_version$")
_PLACEHOLDER_IN_VALUE_RE = re.compile(r"\$\{[^}]+\}")

# Foreign-key declarations live in entity field descriptions and MUST follow
# the canonical `FK -> <Entity>.id[; <annotations>]` prefix (SKILL.md §1.1).
# The regex captures the parent entity name for the reverse-reachability check.
_FK_DESC_RE = re.compile(r"^\s*FK\s*->\s*([A-Za-z_][A-Za-z0-9_]*)\.id\b")


# Instance-name patterns that strongly indicate a negative test (intentional
# violation of role/payload constraints to verify rejection).
_NEGATIVE_NAME_RE = re.compile(
    r"(?:"
    r"_cannot_|_must_not_|"
    r"_missing_(?:auth|required|x_user|header)|"
    r"_invalid_(?:request|enum|role|payload)|"
    r"_returns_(?:4\d\d|invalid_request|unauthenticated|unauthorized|forbidden|not_found)|"
    r"_not_found(?:_returns)?|"
    r"_unauthenticated|_unauthorized|_forbidden|"
    r"_input_ignored|_extra_field|_ignored_input|"
    r"_rejected|_rejects_"
    r")",
    re.IGNORECASE,
)


def is_negative_trigger(call: dict, instance_name: str = "") -> bool:
    """A call is a negative-test trigger when EITHER (i) it captures the error
    envelope (`$.data.error_id` / `$.data.message`), OR (ii) its instance name
    matches a known negative-test pattern (`*_cannot_*`, `*_missing_required_*`,
    `*_returns_4XX`, `*_input_ignored`, etc.). Negative triggers intentionally
    violate role (b) and payload (c) constraints — the test IS the verification
    that the server rejects them. (a) endpoint-declared and (d) capture-resolves
    still apply (you can't reject a non-existent endpoint, and any captured
    fields must still resolve)."""
    caps = call.get("captures") or {}
    if isinstance(caps, dict):
        for v in caps.values():
            if str(v).strip() in _NEGATIVE_TRIGGER_JSONPATHS:
                return True
    if instance_name and _NEGATIVE_NAME_RE.search(instance_name):
        return True
    return False


def validate_capture_path(
    jsonpath: str, ep: Endpoint, entity_fields: dict[str, set[str]]
) -> tuple[bool, str]:
    jp = (jsonpath or "").strip()
    if jp == "$.data":
        return True, "captures whole envelope data"

    m = _CAPTURE_FIELD_RE.match(jp)
    if m:
        field = m.group(1)
        if field in _ERROR_ENVELOPE_FIELDS:
            return True, "error envelope field (always valid per §1.0)"
        # Inline dict output schema: `output: { renewed_count: integer, ... }`
        if ep.output_inline_fields is not None:
            if field in ep.output_inline_fields:
                return True, "inline output schema field"
            return False, (
                f"field `{field}` not in inline output schema "
                f"{sorted(ep.output_inline_fields)}"
            )
        if ep.output_entity is None:
            return False, f"endpoint output is null/scalar; cannot capture `{field}`"
        if ep.output_is_list:
            return False, (
                f"endpoint output is `{ep.output_entity}[]` — capture must use "
                f"`$.data[N].{field}` or `$.data.N.{field}` form"
            )
        fields = entity_fields.get(ep.output_entity)
        if fields is None:
            return False, f"output entity `{ep.output_entity}` not declared in §1.1"
        if field not in fields:
            return False, (
                f"field `{field}` not declared on entity `{ep.output_entity}` in §1.1"
            )
        return True, f"field on `{ep.output_entity}`"

    m = _CAPTURE_LIST_RE.match(jp)
    if m:
        field = m.group(1)
        if not ep.output_is_list:
            return False, (
                f"endpoint output is `{ep.output_entity}` (scalar); "
                f"list-indexed capture invalid"
            )
        fields = entity_fields.get(ep.output_entity or "")
        if not fields:
            return False, f"output entity `{ep.output_entity}` not declared in §1.1"
        if field not in fields:
            return False, f"field `{field}` not declared on `{ep.output_entity}`"
        return True, f"list-indexed field on `{ep.output_entity}`"

    # Complex JSONPath (nested access, filters, etc.) — be lenient.
    return True, f"complex JSONPath (lenient pass): {jp}"


# ---------------------------------------------------------------------------
# Design file walking
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CallSite:
    file_label: str        # "§1.8" or "§1.9"
    rule_or_section: str   # rule_id or section name
    instance_name: str
    location: str          # "setup_api_calls[3]" / "trigger[0]"
    call: dict


def walk_design(
    design_root: dict, file_label: str, top_key: str
) -> Iterator[CallSite]:
    groups = design_root.get(top_key, []) or []
    for grp in groups:
        if not isinstance(grp, dict):
            continue
        group_label = grp.get("rule_id") or grp.get("section") or "<unknown>"
        for inst in grp.get("instances", []) or []:
            if not isinstance(inst, dict):
                continue
            if inst.get("excluded_because"):
                continue
            recipe = inst.get("test_recipe") or {}
            for chain_key in ("setup_api_calls", "trigger"):
                for i, call in enumerate(recipe.get(chain_key) or []):
                    if not isinstance(call, dict):
                        continue
                    yield CallSite(
                        file_label=file_label,
                        rule_or_section=str(group_label),
                        instance_name=str(inst.get("name", "<unnamed>")),
                        location=f"{chain_key}[{i}]",
                        call=call,
                    )


# ---------------------------------------------------------------------------
# Violations
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Violation:
    rule: str
    file_label: str
    rule_or_section: str
    instance_name: str
    location: str
    call_str: str
    detail: str

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def lint_call(
    site: CallSite,
    endpoints: list[Endpoint],
    entity_fields: dict[str, set[str]],
) -> list[Violation]:
    vs: list[Violation] = []
    call = site.call
    call_str = str(call.get("call", "")).strip()
    parsed = parse_call(call_str)
    if not parsed:
        vs.append(
            Violation(
                rule="(a) malformed call string",
                file_label=site.file_label,
                rule_or_section=site.rule_or_section,
                instance_name=site.instance_name,
                location=site.location,
                call_str=call_str,
                detail="expected format `METHOD /path` (METHOD ∈ GET/POST/PUT/PATCH/DELETE)",
            )
        )
        return vs

    method, path = parsed
    ep = find_endpoint(method, path, endpoints)
    negative = is_negative_trigger(call, site.instance_name)

    # (a) endpoint declared
    if ep is None:
        vs.append(
            Violation(
                rule="(a) endpoint not declared in §1.5",
                file_label=site.file_label,
                rule_or_section=site.rule_or_section,
                instance_name=site.instance_name,
                location=site.location,
                call_str=call_str,
                detail=(
                    f"no §1.5 endpoint matches ({method}, {path}). "
                    "Fix via SKILL.md L491 priority ladder: (1) compose existing "
                    "endpoints, (2) add a general business endpoint to §1.5, "
                    "(3) add a `/_<name>` test-driving endpoint."
                ),
            )
        )
        return vs  # downstream checks need a matched endpoint

    # (e) OCC version fields in payload MUST be dynamic.
    #     Applies universally (positive AND negative tests). A negative test
    #     that wants to provoke ERR_STALE_VERSION should still use an expression
    #     like `${w_v_pre_seat} - 1`, not a bare literal — bare literals collide
    #     with whatever value the running implementation actually holds, which
    #     undermines the test's polarity.
    payload_for_occ = call.get("payload")
    if isinstance(payload_for_occ, dict):
        for key, val in payload_for_occ.items():
            if not _OCC_VERSION_KEY_RE.match(str(key)):
                continue
            if isinstance(val, str) and _PLACEHOLDER_IN_VALUE_RE.search(val):
                continue
            vs.append(
                Violation(
                    rule="(e) expected_*_version must be a ${var}, not a literal",
                    file_label=site.file_label,
                    rule_or_section=site.rule_or_section,
                    instance_name=site.instance_name,
                    location=site.location,
                    call_str=call_str,
                    detail=(
                        f"`{key}: {val!r}` is a hardcoded value. OCC version "
                        f"fields can only originate from a server response — "
                        f"add `captures: {{ <pname>_v: $.data.version }}` on a "
                        f"prior call against the parent (or on the parent's "
                        f"create response when the chain is cascade-free), "
                        f"then write `{key}: ${{<pname>_v}}`. Even a literal "
                        f"that 'looks right' silently goes stale once any §1.3 "
                        f"transition or §1.7 cascade bumps the parent's version "
                        f"between its creation and this call."
                    ),
                )
            )

    # (b)+(c) are skipped for negative-test triggers — the test is verifying the
    # endpoint REJECTS this exact payload/role combination; flagging it would be
    # a tautological false positive. (a) and (d) still apply.
    if negative:
        captures = call.get("captures") or {}
        if isinstance(captures, dict):
            for var, jp in captures.items():
                ok, reason = validate_capture_path(str(jp), ep, entity_fields)
                if not ok:
                    vs.append(
                        Violation(
                            rule="(d) capture JSONPath unresolvable",
                            file_label=site.file_label,
                            rule_or_section=site.rule_or_section,
                            instance_name=site.instance_name,
                            location=site.location,
                            call_str=call_str,
                            detail=f"captures.{var} = `{jp}` — {reason}",
                        )
                    )
        return vs

    # (b) role allowed
    role = str(call.get("as", "")).strip()
    if not role:
        vs.append(
            Violation(
                rule="(b) `as:` role missing",
                file_label=site.file_label,
                rule_or_section=site.rule_or_section,
                instance_name=site.instance_name,
                location=site.location,
                call_str=call_str,
                detail="every call must specify an `as:` role per §1.8 schema",
            )
        )
    elif role not in ep.roles:
        vs.append(
            Violation(
                rule="(b) role not allowed by §1.5",
                file_label=site.file_label,
                rule_or_section=site.rule_or_section,
                instance_name=site.instance_name,
                location=site.location,
                call_str=call_str,
                detail=(
                    f"`as: {role}` not in §1.5 roles for {method} {ep.path_template} "
                    f"(allowed: {sorted(ep.roles)})"
                ),
            )
        )

    # (c) payload shape
    payload = call.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        vs.append(
            Violation(
                rule="(c) payload not a mapping",
                file_label=site.file_label,
                rule_or_section=site.rule_or_section,
                instance_name=site.instance_name,
                location=site.location,
                call_str=call_str,
                detail=f"payload must be a dict, got {type(payload).__name__}",
            )
        )
    else:
        allowed = ep.required_inputs | ep.optional_inputs
        unknown = set(payload.keys()) - allowed
        if unknown:
            vs.append(
                Violation(
                    rule="(c) payload key not declared in §1.5 input",
                    file_label=site.file_label,
                    rule_or_section=site.rule_or_section,
                    instance_name=site.instance_name,
                    location=site.location,
                    call_str=call_str,
                    detail=(
                        f"unknown payload key(s) {sorted(unknown)} for "
                        f"{method} {ep.path_template} "
                        f"(input: {sorted(allowed) or 'no body fields'})"
                    ),
                )
            )
        missing = ep.required_inputs - set(payload.keys())
        if missing:
            vs.append(
                Violation(
                    rule="(c) required input field missing from payload",
                    file_label=site.file_label,
                    rule_or_section=site.rule_or_section,
                    instance_name=site.instance_name,
                    location=site.location,
                    call_str=call_str,
                    detail=(
                        f"required field(s) {sorted(missing)} missing for "
                        f"{method} {ep.path_template}"
                    ),
                )
            )

    # (d) captures
    captures = call.get("captures") or {}
    if isinstance(captures, dict):
        for var, jp in captures.items():
            ok, reason = validate_capture_path(str(jp), ep, entity_fields)
            if not ok:
                vs.append(
                    Violation(
                        rule="(d) capture JSONPath unresolvable",
                        file_label=site.file_label,
                        rule_or_section=site.rule_or_section,
                        instance_name=site.instance_name,
                        location=site.location,
                        call_str=call_str,
                        detail=f"captures.{var} = `{jp}` — {reason}",
                    )
                )
    return vs


# ---------------------------------------------------------------------------
# Check (f): FK reverse-reachability — scaffold-level
# ---------------------------------------------------------------------------


def extract_fks(scaffold: dict) -> list[tuple[str, str, str]]:
    """Walk §1.1 entities and pull every (child_entity, fk_field, parent_entity)
    triple. An FK is any field whose `description:` matches the canonical
    `^FK -> <Parent>.id\\b` prefix (SKILL.md §1.1)."""
    out: list[tuple[str, str, str]] = []
    for ent in scaffold.get("entities", []) or []:
        if not isinstance(ent, dict):
            continue
        child = str(ent.get("name", "")).strip()
        if not child:
            continue
        for f in ent.get("fields", []) or []:
            if not isinstance(f, dict):
                continue
            desc = str(f.get("description", ""))
            m = _FK_DESC_RE.match(desc)
            if not m:
                continue
            field_name = str(f.get("name", "")).strip()
            parent = m.group(1)
            if field_name and parent:
                out.append((child, field_name, parent))
    return out


def derive_entity_collection_segments(
    endpoints: list[Endpoint], api_prefix: str
) -> dict[str, str]:
    """Infer each entity's URL collection segment from §1.5.

    Heuristic: a 'single-resource GET' is a GET endpoint whose path is
    `<api_prefix>/<segment>/{id}` (exactly two segments under the prefix,
    the second being a templated id) and whose `output_entity` is the
    entity name (non-list). The `<segment>` is taken as that entity's
    canonical collection name. Only the first matching segment wins."""
    out: dict[str, str] = {}
    prefix = api_prefix.rstrip("/")
    for ep in endpoints:
        if ep.method != "GET":
            continue
        if ep.output_is_list or not ep.output_entity:
            continue
        path = ep.path_template.rstrip("/")
        if not path.startswith(prefix + "/"):
            continue
        rest = path[len(prefix) + 1:]
        parts = rest.split("/")
        if len(parts) == 2 and _PLACEHOLDER_SEG_RE.match(parts[1]):
            out.setdefault(ep.output_entity, parts[0])
    return out


def lint_fk_reverse_reachability(
    scaffold: dict, endpoints: list[Endpoint]
) -> list[Violation]:
    """Check (f): every FK declared in §1.1 has a reverse-reachability GET
    endpoint in §1.5.

    Two endpoint forms satisfy the rule:
      1. Sub-resource: `GET /<parent-collection>/{id}/<child-segment>` with
         `output: <Child>` (1:1) or `output: <Child>[]` (1:N).
      2. Filtered list: `GET /<child-collection>` returning `<Child>[]`
         with the FK field declared in `input:` (required or optional).

    The "child carries the FK to parent" convention from §1.1 means the
    child→parent direction is trivially walkable (read child, look at
    `parent_id`); this check enforces that the parent→child direction is
    also explicitly walkable, closing the FK graph so cascade-created
    resources cannot become dangling pointers."""
    api_prefix = str(scaffold.get("api_prefix", "")).strip()
    prefix = api_prefix.rstrip("/")
    fks = extract_fks(scaffold)
    if not fks:
        return []
    segs = derive_entity_collection_segments(endpoints, api_prefix)
    violations: list[Violation] = []
    for child, fk_field, parent in fks:
        parent_seg = segs.get(parent)
        child_seg = segs.get(child)

        sub_resource_ok = False
        if parent_seg:
            parent_prefix_path = f"{prefix}/{parent_seg}/{{id}}/"
            for ep in endpoints:
                if ep.method != "GET":
                    continue
                if not ep.path_template.startswith(parent_prefix_path):
                    continue
                if ep.output_entity == child:
                    sub_resource_ok = True
                    break

        filtered_list_ok = False
        if child_seg:
            child_list_path = f"{prefix}/{child_seg}"
            for ep in endpoints:
                if ep.method != "GET":
                    continue
                if ep.path_template.rstrip("/") != child_list_path:
                    continue
                if not (ep.output_entity == child and ep.output_is_list):
                    continue
                if fk_field in (ep.required_inputs | ep.optional_inputs):
                    filtered_list_ok = True
                    break

        if sub_resource_ok or filtered_list_ok:
            continue

        detail_lines = [
            f"FK `{child}.{fk_field} -> {parent}.id` has no reverse-reachability "
            f"GET endpoint in §1.5. Given a `{parent}.id`, a PRD-only reader "
            f"cannot discover the associated {child}(s) through any declared "
            f"endpoint, leaving the new {child} as a dangling pointer.",
            "Add one of:",
        ]
        if parent_seg:
            detail_lines.append(
                f"  - Sub-resource: `GET {prefix}/{parent_seg}/{{id}}/<segment>` "
                f"returning `output: {child}` (1:1) or `output: {child}[]` (1:N)."
            )
        else:
            detail_lines.append(
                f"  - Sub-resource: `GET <prefix>/<{parent}-collection>/{{id}}"
                f"/<segment>` returning `output: {child}` or `output: {child}[]` "
                f"(note: could not infer {parent}'s collection segment from §1.5; "
                f"ensure `GET <prefix>/<{parent}-collection>/{{id}}` is declared)."
            )
        if child_seg:
            detail_lines.append(
                f"  - Filtered list: `GET {prefix}/{child_seg}` declaring "
                f"`{fk_field}?` in `input:` and returning `output: {child}[]`."
            )
        else:
            detail_lines.append(
                f"  - Filtered list: `GET <prefix>/<{child}-collection>` "
                f"declaring `{fk_field}?` in `input:` returning "
                f"`output: {child}[]` (note: could not infer {child}'s "
                f"collection segment from §1.5)."
            )
        violations.append(
            Violation(
                rule="(f) FK_REVERSE_UNREACHABLE",
                file_label="SCAFFOLD",
                rule_or_section="§1.1↔§1.5 FK reverse-reachability",
                instance_name=f"{child}.{fk_field} -> {parent}",
                location=f"entities[name={child}].fields[name={fk_field}]",
                call_str="(scaffold-level check, no call)",
                detail="\n".join(detail_lines),
            )
        )
    return violations


# ---------------------------------------------------------------------------
# CLI / IO
# ---------------------------------------------------------------------------


def _load_yaml(p: Path) -> dict:
    try:
        with p.open("r") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: file not found: {p}", file=sys.stderr)
        sys.exit(2)
    except yaml.YAMLError as e:
        print(f"ERROR: yaml parse failed for {p}: {e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"ERROR: {p} did not parse to a mapping", file=sys.stderr)
        sys.exit(2)
    return data


def _resolve_paths(argv: list[str]) -> tuple[Path, Path, Path]:
    if len(argv) == 1:
        d = Path(argv[0])
        if not d.is_dir():
            print(f"ERROR: {d} is not a directory", file=sys.stderr)
            sys.exit(2)
        return (
            d / "SCAFFOLD.yaml",
            d / "SCAFFOLD_DIFFICULTY_DESIGN.yaml",
            d / "SCAFFOLD_CORNER_DESIGN.yaml",
        )
    if len(argv) == 3:
        return Path(argv[0]), Path(argv[1]), Path(argv[2])
    print(
        "ERROR: pass either <task_dir> or 3 explicit yaml paths "
        "(SCAFFOLD, DIFFICULTY_DESIGN, CORNER_DESIGN)",
        file=sys.stderr,
    )
    sys.exit(2)


def _render_text(
    violations: list[Violation], stats: dict, paths: tuple[Path, ...]
) -> str:
    lines: list[str] = []
    lines.append("SCAFFOLD §1.8/§1.9 -> §1.5 lint report")
    lines.append("=" * 60)
    lines.append(f"  SCAFFOLD:           {paths[0]}")
    lines.append(f"  Difficulty design:  {paths[1]}")
    lines.append(f"  Corner design:      {paths[2]}")
    lines.append("")
    lines.append("Coverage")
    lines.append(f"  §1.5 endpoints declared:    {stats['n_endpoints']}")
    lines.append(f"  §1.1 entities declared:     {stats['n_entities']}")
    lines.append(f"  §1.8 instances scanned:     {stats['n_difficulty_instances']}")
    lines.append(f"  §1.9 instances scanned:     {stats['n_corner_instances']}")
    lines.append(f"  Calls scanned (§1.8+§1.9):  {stats['n_calls']}")
    lines.append("")
    if not violations:
        lines.append(
            "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 "
            "and all §1.1 FKs have reverse-reachability in §1.5."
        )
        return "\n".join(lines)

    by_rule: dict[str, int] = {}
    for v in violations:
        by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
    lines.append(f"VERDICT: {len(violations)} violation(s)")
    for rule, n in sorted(by_rule.items()):
        lines.append(f"  · {n:>3}  {rule}")
    lines.append("")
    lines.append("Detail")
    lines.append("-" * 60)
    for i, v in enumerate(violations, 1):
        lines.append(f"[{i}] {v.file_label} / {v.rule_or_section} / {v.instance_name}")
        lines.append(f"      location: {v.location}")
        lines.append(f"      call:     {v.call_str}")
        lines.append(f"      rule:     {v.rule}")
        lines.append(f"      detail:   {v.detail}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Lint SCAFFOLD §1.8/§1.9 against §1.5 endpoint table.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "paths",
        nargs="+",
        help="Either <task_dir> or 3 yaml paths "
        "(SCAFFOLD, DIFFICULTY_DESIGN, CORNER_DESIGN)",
    )
    ap.add_argument(
        "--json", action="store_true", help="emit JSON instead of text"
    )
    ap.add_argument(
        "--warn-only", action="store_true", help="exit 0 even on violations"
    )
    args = ap.parse_args()

    scaffold_p, diff_p, corner_p = _resolve_paths(args.paths)
    scaffold = _load_yaml(scaffold_p)
    diff_design = _load_yaml(diff_p)
    corner_design = _load_yaml(corner_p)

    endpoints = load_endpoints(scaffold)
    entity_fields = load_entity_fields(scaffold)

    def _count_active(root: dict, top_key: str) -> int:
        n = 0
        for g in root.get(top_key, []) or []:
            if not isinstance(g, dict):
                continue
            for i in g.get("instances", []) or []:
                if isinstance(i, dict) and not i.get("excluded_because"):
                    n += 1
        return n

    n_diff = _count_active(diff_design, "scaffold_difficulty_design")
    n_corner = _count_active(corner_design, "scaffold_corner_design")

    violations: list[Violation] = []
    n_calls = 0
    for site in walk_design(diff_design, "§1.8", "scaffold_difficulty_design"):
        n_calls += 1
        violations.extend(lint_call(site, endpoints, entity_fields))
    for site in walk_design(corner_design, "§1.9", "scaffold_corner_design"):
        n_calls += 1
        violations.extend(lint_call(site, endpoints, entity_fields))

    # (f) Scaffold-level FK reverse-reachability check — runs once across
    #     §1.1 entities vs §1.5 endpoints, independent of §1.8/§1.9 calls.
    violations.extend(lint_fk_reverse_reachability(scaffold, endpoints))

    stats = {
        "n_endpoints": len(endpoints),
        "n_entities": len(entity_fields),
        "n_difficulty_instances": n_diff,
        "n_corner_instances": n_corner,
        "n_calls": n_calls,
        "n_violations": len(violations),
    }

    if args.json:
        out = {
            "paths": {
                "scaffold": str(scaffold_p),
                "difficulty_design": str(diff_p),
                "corner_design": str(corner_p),
            },
            "stats": stats,
            "violations": [v.as_dict() for v in violations],
            "ok": not violations,
        }
        print(json.dumps(out, indent=2))
    else:
        print(_render_text(violations, stats, (scaffold_p, diff_p, corner_p)))

    if violations and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
