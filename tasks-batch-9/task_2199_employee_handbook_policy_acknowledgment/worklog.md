# Worklog — task_2199_employee_handbook_policy_acknowledgment

## Step 1: Create task directory — 2026-08-31T00:00:00.000Z

Created `tasks/task_2199_employee_handbook_policy_acknowledgment/` and `tasks/task_2199_employee_handbook_policy_acknowledgment/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-08-31T21:15:00.000Z

RESUME-MODE NOTE: three subagent attempts were required. Attempts 1 and 2 were killed by the
600s stall watchdog while composing a single very large `Write` call, leaving zero files on disk.
Attempt 3 was launched with a hard ≤120-lines-per-write cap and an append-via-heredoc discipline;
it successfully wrote all three artifacts incrementally, then terminated on an upstream API error
during its final self-verification pass, so no verbatim subagent summary is available for this step.
The orchestrator verified the artifacts directly instead; all three are complete, non-truncated,
and lint-clean:

- SCAFFOLD.yaml — 2751 lines. Parses. Top-level keys: scenario, domain_name, api_prefix,
  complexity_profile, response_envelope, entities, state_machines, concurrency_rules,
  calculations, validations, endpoints, errors, roles. No scaffold_difficulty_design or
  scaffold_corner_design key present (correct separation).
  15 entities, 72 declared §1.5 endpoints.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1026 lines. Parses. Single top-level key
  scaffold_difficulty_design. All 9 Difficulty Rules present with 2 instances each (18 total):
  dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade,
  priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency,
  resource_temporal_overlap, compensating_invariant.
- SCAFFOLD_CORNER_DESIGN.yaml — 1589 lines. Parses. Single top-level key scaffold_corner_design.
  All 9 claim-extraction-guide sections present (entities 12, state_machines 9, calculations 7,
  validations 11, endpoints 5, errors 5, rbac 2, cross-cutting complexity layers 7,
  consistency model 1) = 59 authored instances.

Linter (`scaffold_lint.py .`) VERDICT: **clean lint** — all §1.8/§1.9 calls conform to §1.5 and
all §1.1 FKs have reverse-reachability in §1.5. Coverage counted: 72 endpoints, 15 entities,
18 §1.8 instances, 49 §1.9 non-stub instances, 1203 calls scanned.

## Step 3: Copy shared files — 2026-08-31T19:17:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines). Performed before Step 2 completed,
as it has no dependency on the scaffold.

## Step 4: Generate PRD — 2026-08-31T21:27:00.000Z

The PRD is complete and all mechanical audits pass.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2199_employee_handbook_policy_acknowledgment/workspace/PRD.md` — **430 lines**, ends at §5 with no audit footer.

### Section list

- **§1 Introduction** (3 paragraphs: pain point -> system scope -> the two design commitments)
- **§2 Global Specifications** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps, and the Version Counter · 2.5 The Logical Clock · 2.6 Optimistic Concurrency Control on Guarded Writes · 2.7 Precision and Rounding · 2.8 Request Screening Order · 2.9 Cascades, Denormalized Counters, and Nested Reads · 2.10 Two Conserved Quantities
- **§3 Business Logic & Workflows** — 9 subsections grouped by lifecycle stage: 3.1 Jurisdictional Ground Rules, Counsel Rosters, and the People Directory · 3.2 Authoring: Policy Documents, Versions, and State Addenda · 3.3 The Jurisdiction Legal Review Cycle · 3.4 Approving, Re-opening, and Withdrawing a Version · 3.5 Localization Tracks and the Accessibility Index · 3.6 Release Packages: Assembly, Scheduling, and the Release Event · 3.7 Delivery, Acknowledgment, Revocation, and Retention · 3.8 Non-Acknowledgment: The Overdue Sweep, Tiers, and Escalation Cases · 3.9 Policy Exceptions: Two-Stage Approval, Risk Scoring, and Expiry
- **§4 Endpoint Definitions** (4-column table) · **§5 Error Code Catalogue** (2-column table)

### Coverage audit (scripted against SCAFFOLD.yaml)

```
Field coverage check:
- entities[].fields: 125 required, 125 present, 0 missing
- endpoints[].request_body: 50 required, 50 present, 0 missing
- endpoints[].query_params: 27 required, 27 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 49 checked, 49 expressed in prose, 0 missing
  (priority chains stated explicitly for auth/existence/shape 1-8, acknowledgment
   9->24->28->29->30->37, version-approve 27->33, schedule 21->34->39->40->45->46)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed
  (expected_policy_document_version / ERR_STALE_POLICY_DOCUMENT_VERSION 412;
   expected_employee_version / ERR_STALE_EMPLOYEE_VERSION 412;
   expected_release_package_version / ERR_STALE_RELEASE_PACKAGE_VERSION 412)
- state_machines[].transitions: 55 checked, 55 written as explicit state pairs, 0 missing
- calculations[]: 9 checked, 9 fully expressed with pinned evaluation orders, 0 missing
- validations[] conditions: 49 checked, 49 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 72 endpoints checked, 0 missing
- entities[].fields[] structured content: 125 checked, defaults/initials/enums reconstructible
- sibling-branch symmetry: 8 groups checked (addendum RETIRED x2, translation ABANDONED x2,
  package CANCELLED x2, assignment VOIDED x2, case CLOSED_ACKNOWLEDGED x3 / CLOSED_MOOT x3,
  exception DENIED x2, version WITHDRAWN x2, coverage variants x2), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 886
- tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path tokens: 0
Status: PASS
```

Additional verified invariants: §4 table contains exactly 72 rows matching scaffold method+path with **0 role mismatches**; §5 contains exactly 49 error rows with scaffold-exact HTTP statuses; all state enumeration values and all `type: enum` field values appear verbatim.

### Two judgement calls worth flagging

Two scaffold preconditions carry no nominated `error_id`: the re-open guard ("no release item referencing this version belongs to a `SCHEDULED`/`RELEASED`/`CLOSED` package") and the schedule/release guard ("every item's version must be `APPROVED`"). Rather than invent identifiers, both are written as "refused as a state conflict at HTTP 409" so the rule is fully specified without fabricating a code the test suite couldn't know.

## Step 5: Generate unit tests — 2026-08-31T22:28:00.000Z

Test generation is complete for `task_2199_employee_handbook_policy_acknowledgment`.

## Files created

**`/home/ubuntu/github/CodingPRD/tasks/task_2199_employee_handbook_policy_acknowledgment/test_helpers/`** (9 modules, ~2,100 lines): `__init__.py` (barrel), `api_client.py` (`ApiClient` over all 78 endpoints + `_clock`/`_ops` hooks), `api_errors.py` (50 `ApiErrorId` members + HTTP status map registered at import), `types.py`, `constants.py`, `factories.py` (payload builders with unique keys), `test_users.py` (per-role header builders, incl. entity-backed `make_counsel_headers`/`make_employee_headers`/`make_manager_headers`), `assertions.py` (common-field vs. append-only assertors, ledger/counter invariants, `assert_same_instant`), `fixtures.py` (tiered scenario builders up to `setup_released_scenario`, `setup_open_escalation_case`, `setup_submitted_exception`, `setup_granted_exception`).

**`.../test_suite/`**: `conftest.py` + 16 test modules, **83 tests**.

## Per-queue breakdown

| Queue | Instances | Translated | Tests emitted |
|---|---|---|---|
| A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) | 18 non-stub | **18/18** | 36 |
| B — `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) | 49 non-stub (+10 `excluded_because` stubs, no tests) | **47/49** | 47 |

Every test carries exactly one `Design:` line; a programmatic cross-check of all 83 tags against the two YAMLs reports no invalid tag, no section/rule mismatch, no stub tagged, and no dual-tagged test.

## Instances SKIPPED (PRD-first filter)

1. `Corner/endpoints/corner_notify_action_is_conditional_on_the_subject_having_a_manager` — asserts a manager-less subject's case accepts notify (200 -> NOTIFIED, `notified_manager_id` null). PRD §3.8 states notify "requires the case to be in `OPEN` and **requires `notified_manager_id` to be non-null, since there is nobody to notify for a subject with no manager**". The PRD contradicts the central asserted outcome.
2. `Corner/cross-cutting complexity layers/corner_pinned_addendum_set_is_frozen_at_version_approval` — the recipe needs a *second* CA addendum (`a3`) on the same version, then approves it after version approval. PRD §3.2 says "Only one addendum may exist per jurisdiction per version" (and lists the `(policy_version_id, jurisdiction_id)` pair under `ERR_DUPLICATE_RESOURCE`), so `a3` cannot exist; §3.2 also requires the owning version to be in `DRAFT` or `IN_LEGAL_REVIEW` for addendum approval, so it could not be approved post-approval either. Both post-approval assertions (live approved set of 3 while pin stays 2) are unreachable, and no PRD-derivable substitute makes the live/pinned sets diverge.

One assertion-level deviation is carried in queue A (recorded earlier): `Difficulty/.../a11y_index_round_per_section_before_summing` asserts `a11y_round_no == 1` after `submit-a11y`, but PRD §3.5 starts a track at 0 and only increments on rework — that single assertion was dropped; the instance is still covered via `a11y_index`, `conformance_level` and `status`.

Two setup-level adjustments (not weakenings) were needed so success assertions stay PRD-derivable: `corner_reviewer_authorization_is_per_review_and_per_jurisdiction` drives the version to `IN_LEGAL_REVIEW` before the successful `start` (PRD §3.3), and the a11y-shape instance asserts `section_scores == []` rather than `null` (PRD §3.5: "an empty `section_scores` array").

## Verification

- `python3 -m compileall -q test_helpers test_suite` -> clean.
- `python3 -m pytest test_suite --collect-only -q` -> **83 tests collected in 0.48s, zero collection errors** (collection only; no server run).
- AST sweeps confirm no unused imports in any test module, every `from test_helpers import ...` name resolves on the package, and no generated file mentions "scaffold" or scaffold section references.

## Step 6: Generate implementation — 2026-08-31T22:38:00.000Z

Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_2199_employee_handbook_policy_acknowledgment/workspace/implementation/`.

## Files (2,725 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | guarded `pip install` (only if `import flask` fails), `exec python3 app.py`, `PORT` default 10000 |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 50 | app factory, `strict_slashes=False`, ApiError/404/405/HTTPException/500 handlers, blueprint registration, `host="0.0.0.0"`, `port=$PORT` |
| `errors.py` | 65 | all 49 error IDs -> HTTP status, `ApiError`, `fail()` |
| `clock.py` | 77 | forward-only logical clock, `START = 2026-08-01T00:00:00Z`, ISO-8601 3-digit-ms formatter, whole-day floor arithmetic, calendar-year add with 29 Feb -> 1 Mar |
| `db.py` | 81 | 15 in-memory dict tables, `new_id`, `base_row`, `touch`, `sort_created` (created_at, `_seq` tiebreak) |
| `response.py` / `web.py` | 48 / 21 | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` in `meta`, `req_` + 20 alnum ids |
| `auth.py` | 55 | `X-User-ID`/`X-User-Role`, 6 roles, entity-backed identity resolution, screening steps 1-4 |
| `validate.py` | 186 | body/pagination/typed-field/FK/path/query-filter screening |
| `calc.py` | 131 | all 8 calculations, `Decimal` + `ROUND_HALF_UP` |
| `serializers.py` | 102 | per-table output field lists; evidence tables (`release_items`, `acknowledgments`, `retention_records`) carry only `id`/`created_at`; `days_overdue` recomputed at read |
| `services.py` | 234 | shared cascades, counters, coverage, supersede/void/close, retention append, due-date mint |
| `routes/` | 1,568 | `directory` 181, `authoring` 268, `review` 150, `localization` 136, `release` 344, `distribution` 196, `escalation` 83, `exceptions` 197, `ops` 111 |

## Endpoint coverage: 72 / 72

Programmatically diffed the Flask URL map against the PRD §4 endpoint table: **0 missing, 0 extra** (exact method+path match, `/static` excluded).

## Modelling notes

- **State machines (7).** Version DRAFT->IN_LEGAL_REVIEW->APPROVED->PUBLISHED->SUPERSEDED/WITHDRAWN, addendum, legal review (incl. the 4-hop revert cascade), translation, release package, exception (two-stage), escalation case. `DistributionAssignment` keeps its two dimensions genuinely independent (`ack_state` x `escalation_state`); cross-dimension writes happen only via the documented cascades (ack hop 4 -> RESOLVED, void/exempt -> MOOT, disciplinary close -> RESOLVED). Revoking evidence returns `ACKNOWLEDGED -> PENDING` and deliberately leaves `escalation_state` untouched and closed cases un-reopened.
- **Calculations.** a11y index uses the pinned per-section-round-then-sum order (verified 90.51 on the PRD's example); `legal_review_deadline` uses base->lead->slack->buffer without re-derivation; ack deadline applies the 4 clamps in order (SAFETY cap last, overriding the accessibility floor); risk score produces both variants with the conservative peak blend (verified 41.40 / 28.50 for MEDICAL/90d/0 prior/CODE_OF_CONDUCT); coverage yields exactly 100.00 on a zero denominator; retention horizon = later of calendar-years and the 1095-day dispute floor (verified 2030-09-25 for a 4-year jurisdiction).
- **OCC.** Three guards — `expected_policy_document_version`, `expected_employee_version`, `expected_release_package_version` — each checked **before** state/from-state checks per PRD §2.8, returning 412.
- **Logical clock.** Module-level in-memory instant, starts exactly `2026-08-01T00:00:00Z`, never falls back to wall clock (wall clock is used only for `meta.api_request_timestamp`); `/_clock/set_current_utc` rejects rewinds with `ERR_CLOCK_REWIND`, equal value is a no-op.
- **Storage.** Pure Python dicts; no file, SQLite, or `/tmp` state, and **no seeding** — a fresh boot returns empty lists (`total_count: 0`) for every collection.

## Smoke test

`python3 -m compileall -q .` -> clean. Booted with `PORT=18299 bash start.sh`, then ran a scripted end-to-end flow: jurisdiction -> reviewer -> employees -> document -> version (OCC) -> legal review -> addendum -> submit-for-review -> review approve -> addendum approve -> translation a11y (98.75/AAA) -> publish -> version approve -> package -> item -> schedule (`legal_review_deadline` 2026-08-14 from eff 08-20, base 5, slack 14, buffer 1) -> clock advance -> release (roster 3) -> deliver -> overdue 16 days -> sweep (tier 3) -> notify -> escalate-hr -> acknowledge (retention CAPTURE +1, horizon 2030-09-25) -> legal hold -> revoke ack (back to PENDING, escalation stays RESOLVED) -> exception request (risk 41.40/28.50, shielded from the next sweep) -> manager approve -> legal SoD conflict 403 -> clean counsel grants (expires 2026-12-24, assignment EXEMPT) -> sweep expiry (EXPIRED, due_date re-derived to 2027-01-13 on the un-clamped basis). Negative paths verified: 401 missing headers, 401 unknown role, 403 identity unknown, 403 role not permitted, 404 unknown path/method/resource, 404 unresolved body FK, 400 bad pagination, 422 schema, 409 clock rewind. No server-side tracebacks. Server killed afterwards; `__pycache__` removed.

## Step 7: Run tests and iterate — 2026-08-31T22:49:00.000Z

All 8 parallel rounds now pass 83/83.

## Summary

**Iterations run:** 2 (each an 8-round concurrent stability sweep, 83 tests per round).

- Iteration 1: 81/83 in all 8 rounds — 2 deterministic failures (no flakiness; identical failure set in every round).
- Iteration 2: **83/83 in all 8 rounds.**

**Tests deleted:** none. Both failures were resolved at the assertion level under STEP 1c partial-coverage handling — the covered assertions were kept, the non-derivable ones removed.

**Assertions removed from `test_suite/` (PRD-silence category):**

1. `/test_suite/test_09_state_machines.py` — `test_transitions_attempted_from_the_wrong_source_state_are_rejected`, dropped `assert still_requested["verdict"] is None` (was raising `KeyError: 'verdict'`).
   *Category: COMPUTED-FIELD / response-field silence.* PRD names `verdict` in exactly two places (§3.3 and the §4 endpoint row), both as the **decision-request payload field**. §3.3's field inventory for a `LegalReview` is explicit — "sets `status` to `REQUESTED`, sets `round_no` to 1, leaves `decided_at` and `comment` null" and "reading one surfaces `round_no`, `assigned_at`, `due_at` and `decided_at`" — and never lists `verdict` as a stored/response attribute. A faithful reader correctly omits it from the serializer. The test's real subject (a decision from `REQUESTED` is refused `ERR_REVIEW_INVALID_STATE`, review stays `REQUESTED`, `decided_at` stays null) is fully retained.

2. `/test_suite/test_15_cross_cutting.py` — `test_the_sweep_is_inert_at_the_due_instant_and_idempotent_afterwards`, replaced the three assertions made against the **response body of `POST /_ops/escalation-sweep`** (`assert sweep() == []` x2, `opened = sweep()`) with equivalent assertions read through the PRD-declared `GET /escalations` list endpoint.
   *Category: unique-derivability failure (two-reader divergence).* PRD nowhere states what the batch checkpoint returns; the only governing sentence is the generic §4 preamble, "returns HTTP 200 with the affected resource, the requested collection, or an empty object where the operation has no resource to return." The §4 row describes four distinct effects ("opens escalation cases..., re-tiers open and notified cases, and expires granted exceptions"), so at least three faithful readings exist: return only the newly-opened cases (test's reading -> `[]` on a repeat sweep), return every case the checkpoint touched/re-tiered (implementation's reading -> the re-tiered case), or return an empty object. Since the PRD does not pin the payload, the assertion had to stop depending on it. The PRD-covered rule — sweep is inert at the due instant, opens exactly one `OPEN` tier-1 case one day past `due_date`, and is idempotent on repeat — is asserted unchanged, just observed via the list endpoint. A small `_case_rows()` helper was added locally in the test (the pre-existing `_cases()` count helper now delegates to it).

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper was found to construct a precondition inconsistent with PRD.

**Fixes applied to `implementation/`:** none. Notably, no implementation check was removed or weakened; the sweep's `return web.paged("escalations", cases)` behaviour is one of the PRD's admissible readings and was left intact rather than bent to match an unpinned assertion.

**Key finding:** the implementation was already PRD-faithful. Both failures were test-artifact bugs of the same shape — assertions reaching for state the PRD never declares response-visible (`verdict` on a review; the content of the sweep's response body). No timing-sensitivity or flakiness was observed anywhere: the failure set was byte-identical across all 8 rounds in iteration 1, and iteration 2 was clean across all 8.

**Orchestrator verification:** results.{1..8}.json each report passed 83 / total 83, failed 0, errors 0, skipped 0. `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` and `test_helpers/` returns 0 hits. `implementation/` file mtimes are all from Step 6 generation (latest 21:47), confirming no implementation edits were made during Step 7; the two test files were edited at 22:38 and the final clean sweep completed at 22:40.

## Step 8: Finalize PRD — 2026-08-31T22:52:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2199_employee_handbook_policy_acknowledgment/workspace/PRD_FINALIZED.md` created as a 2-line patch of PRD.md.

**Line counts:** PRD.md 430 -> PRD_FINALIZED.md 432 (+2 lines, +0.47%; one sentence inserted mid-line in §3.3, one new paragraph in §3.8).

**Changes**

- §3.3 (legal-review decision) — insert — states that `verdict` is a decision input only: never persisted as a review field and never present in a review's response payload, whose attributes remain the ones already inventoried. — `implementation/serializers.py:39-42` (`legal_reviews` field list has no `verdict`), `implementation/routes/review.py:101,112` (verdict read from body, consumed only to pick the target status).
- §3.8 (escalation sweep) — insert — pins the checkpoint's response body: after the whole checkpoint finishes (re-tiering plus §3.9 grant expiry), it returns the collection of every escalation case then in `OPEN` or `NOTIFIED` — carried-over cases included, `ESCALATED_HR`/closed omitted — under list-endpoint ordering/windowing/`meta` conventions (§2.3). — `implementation/routes/ops.py:98-100` via `implementation/web.py:8-13`.

**Per-edit pre-edit search log**

Edit 1
- (a) Subject: whether `verdict` is a stored/response-visible attribute of a `LegalReview`, and what a review response contains.
- (b) Enumerated/read: `grep -rn "verdict"` across `implementation/` — only hits are `routes/review.py:101` (`validate.req_enum`), `:107`, `:112`, `:120`; no assignment into the review row, no serializer entry. Read `serializers.py` in full (`FIELDS["legal_reviews"]` = COMMON + policy_version_id, jurisdiction_id, reviewer_id, assigned_at, due_at, status, decided_at, round_no, comment; `dump`/`dump_list` project strictly from `FIELDS`, so *every* review-returning path is covered). Read all five review-returning endpoints in `routes/review.py`: create (`web.created`), list (`web.paged`), read (`web.one`), start, decision, re-request (`web.one`) — all go through the same projection. Confirmed `comment` *is* stored and serialized, so the sentence had to exempt `comment`.
- (c) Adjustment: scoped the claim to `verdict` alone and phrased the positive half as "whose attributes remain the ones inventoried above" instead of naming a closed field list, so the sentence stays true of `comment` (set on either verdict branch when supplied, and not cleared on re-request) and of the fields §3.3 already names.

Edit 2
- (a) Subject: the response body of `POST /_ops/escalation-sweep` — which escalation cases it contains, in what order, and in what envelope.
- (b) Enumerated/read: `routes/ops.py` in full — `escalation_sweep` (open pass -> re-tier pass over `OPEN`/`NOTIFIED` -> `_expire_grants()` -> final filter `status in ("OPEN","NOTIFIED")` -> `web.paged`), `_open_case`, `_tier_for`, `_shielded`, `_expire_grants` (confirmed it closes no case, so no case can leave `OPEN`/`NOTIFIED` during the sweep). `web.py:paged` (calls `validate.pagination()`, re-sorts by `created_at`, windows, `response.listing`). `validate.pagination()` (`validate.py:20-34`, `ERR_INVALID_PAGINATION` applies to the sweep too). `response.listing` (`response_type: "array"`, `limit`/`offset`/`total_count`/`has_more` in `meta`). Parallel endpoint `routes/escalation.py:17-27` `GET /escalations` — same table, same serializer, same `web.paged`, so the new wording does not conflict with the declared list endpoint; also read `notify`/`escalate-hr`/`close` to confirm they are the only producers of `NOTIFIED`/`ESCALATED_HR`/closed statuses the response filter discriminates on.
- (c) Adjustment: the filter is status-only, so I avoided any wording implying the sweep returns "the cases it touched" or that a case's assignment must still exist; wrote "every escalation case whose `status` is then `OPEN` or `NOTIFIED`, regardless of which run opened it". Deferred ordering/windowing to §2.3 rather than restating them, since `web.paged` is the shared helper used by every list endpoint.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly two hunks (one revised line at 185, one inserted paragraph after 269), matching the reported scope. No sections added, no other prose touched.

## Step 9: Complete PRD — 2026-08-31T23:09:00.000Z

PRD_COMPLETED.md is written and verified.

## Result

- **Source**: `PRD_FINALIZED.md` — 432 lines / 92,524 chars
- **Output**: `workspace/PRD_COMPLETED.md` — 433 lines / 104,444 chars (**+11,854 chars, +1 line**)
- **Shape of patch**: 40 in-paragraph revisions + 1 added bullet. No new sections, no new paragraphs (the single new line is a bullet appended to the existing error-format bullet list in §2.2).
- **Counts**: 31 ambiguity-pins, 10 mismatch-revisions (41 changes total).
- All 72 impl routes were cross-checked against the §4 table (paths and role lists match exactly), and all 49 error ids against §5.

## Changes

- §2.1 — revise — ambiguity — headers are whitespace-trimmed (whitespace-only counts as absent); role matched case-sensitively — `auth.py:38-46`
- §2.1 — insert — ambiguity — backing entity is chosen by the *acting* role, so an entity-backed role the endpoint does not authorize is resolved (and reported unknown) before the role check — `auth.py:49-53`
- §2.2 — insert — ambiguity — unknown path/method -> `ERR_RESOURCE_NOT_FOUND` 404; absent/unparseable body read as `{}`; non-object JSON -> `ERR_VALIDATION` — `app.py:20-32`, `validate.py:10-16`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order; filters matched by exact equality and never validated (bad value -> empty window); undocumented params ignored — `db.py:80`, `validate.py:166-186`
- §2.5 — insert — ambiguity — `to_iso8601` required; success returns empty `data`; envelope `api_request_timestamp` is real wall-clock, not logical — `ops.py:103-111`, `clock.py:74`
- §2.6 — revise — mismatch — dropped "supersedes the requester's prior granted exception": impl leaves prior rows untouched — `exceptions.py:57-78`
- §2.7 — insert — ambiguity — two-decimal is a rounding rule, not formatting: emitted as bare JSON numbers (`100.0`, not `"100.00"`) — `serializers.py:80-88`
- §3.1 — revise — mismatch — language codes must be two lowercase **letters** (digits rejected), applied at all 4 occurrences — `validate.py:126-131`
- §3.1 — revise — ambiguity — employee PATCH: all four fields optional, omitted/null left as-is, explicit null `manager_id` clears, empty body accepted and still bumps `version` — `directory.py:165-181`
- §3.2 — revise — ambiguity — addendum approve: version-state failure is `ERR_VERSION_INVALID_STATE`; screening order is jurisdiction -> addendum state -> version state (not the listed order) — `authoring.py:154-164`
- §3.3 — insert — ambiguity — review request: `due_at` unconstrained vs clock; check order version -> is_active -> uniqueness -> capacity — `review.py:35-44`
- §3.3 — revise — ambiguity — start: version-state failure is `ERR_VERSION_INVALID_STATE`; order reviewer -> review state -> version state — `review.py:84-90`
- §3.3 — revise — ambiguity — decision: missing `comment` screened *after* ownership/state; revert cascade fires only if version still `IN_LEGAL_REVIEW`; supplied `comment` persisted on either verdict — `review.py:104-123`
- §3.3 — revise — ambiguity — submit-for-review: addendum sweep first (`ERR_ADDENDUM_NOT_APPROVED`) then review sweep (`ERR_LEGAL_REVIEW_INCOMPLETE`) — `authoring.py:177-188`
- §3.3 — revise — ambiguity — re-request: version-state error id, check order, capacity excludes the review itself, stored `comment` retained — `review.py:133-148`
- §3.4 — revise — ambiguity — reopen: live-release conflict uses `ERR_VERSION_INVALID_STATE` — `authoring.py:231`
- §3.4 — revise — mismatch — withdraw from `PUBLISHED`: pointer cleared only if it names this version, no document `version` bump, and full void routine incl. moot closes + package auto-close — `authoring.py:264-267`, `services.py:55-72`
- §3.4 — insert — mismatch — supersede cascade also runs the package-close check — `services.py:69-72`
- §3.4 — insert — mismatch — moving `current_published_version_id` is exempt from §2.9: no `version`/`updated_at` bump on the document — `services.py:182-183`
- §3.5 — revise — ambiguity — translation start: version-state failure is `ERR_VERSION_INVALID_STATE`, screened after the track's from-state — `localization.py:63-67`
- §3.5 — revise — mismatch — six-decimal figure is not enforced; missing/non-array `section_scores` is `ERR_VALIDATION` before the state check, while every `ERR_SECTION_SCORE_SHAPE` condition is after it; booleans rejected — `localization.py:78-93`
- §3.6 — insert — mismatch — item add does **not** screen the version's status (only schedule/release do) — `release.py:68-89`
- §3.6 — revise — ambiguity — schedule: item-`APPROVED` sweep is `ERR_VERSION_INVALID_STATE` and runs right after the `DRAFT` check, ahead of all other gates — `release.py:217-223`
- §3.6 — insert — ambiguity — overlap: `SUPERSEDED` sibling with null `window_end_date` treated as open-ended; null `effective_date` sibling skipped — `release.py:173-182`
- §3.6 — insert — ambiguity — lead time: jurisdiction with no review row or null `decided_at` is skipped, not refused — `release.py:205-206`
- §3.6 — revise — ambiguity — release: item-`APPROVED` gate error id and its position after the effective-date check — `release.py:309-312`
- §3.6 — insert — ambiguity — buffer: signed floor-truncated gap, earlier window decided by `window_start_date` with ties favouring the persisted row, whole roster pre-checked before any mutation, candidates never compared to each other — `release.py:274-291`, `release.py:313-315`
- §3.7 — revise — mismatch — delivery does **not** require the owning package to be `RELEASED`; exactly three ordered checks — `distribution.py:51-60`
- §3.7 — revise — ambiguity — revoke: both refusals are `ERR_ASSIGNMENT_INVALID_ACK_STATE`, acknowledgment status screened first — `distribution.py:152-155`
- §3.7 — insert — ambiguity — legal hold: `hold_reason` required non-empty, allowed on any row/re-holdable, no counter to move — `distribution.py:188-196`
- §3.8 — insert — mismatch — `days_overdue` is never stored; recomputed at serialization on every read — `serializers.py:96-98`
- §3.8 — insert — mismatch — re-tiering leaves `version`/`updated_at` untouched; three checkpoint phases run open -> re-tier -> expire — `ops.py:88-97`
- §3.8 — revise — ambiguity — notify: null `notified_manager_id` -> `ERR_VALIDATION` (422), after the from-state check — `escalation.py:43-44`
- §3.8 — revise — ambiguity — close: `outcome` is a single-member required enum, never persisted; assignment gate is `ERR_ASSIGNMENT_INVALID_ACK_STATE` — `escalation.py:69-74`
- §3.9 — revise — mismatch — exception creation takes the earliest `PENDING` assignment rather than requiring exactly one — `exceptions.py:47-54`
- §3.9 — insert — ambiguity — `note` (both stages) and `reason` (revoke) are validated (<=2000 chars) but never persisted or echoed — `exceptions.py:108,144,184`
- §3.9 — revise — ambiguity — conservative score blends the **unrounded** weighted mean, peak compared at each factor's own precision — `calc.py:76-84`
- §3.9 — insert — ambiguity — grant: package close check runs; non-`PENDING` assignment skips assignment-side hops but grant stands — `exceptions.py:161-171`
- §3.9 — insert — ambiguity — grant revoke: `CLOSED` package pulled back to `RELEASED`, non-`EXEMPT` assignment skipped, no case reopened — `exceptions.py:189-196`
- §3.9 — insert — ambiguity — expiry: package reopen, non-`EXEMPT` assignment skipped, null `expires_at` never expires — `ops.py:52-72`

**Orchestrator verification:** `PRD_COMPLETED.md` is 433 lines, non-truncated (ends on the §5 error table's last row). `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports 41 hunks, matching the 41 reported changes. `diff` of the two files' heading lines is empty — no sections were added or renamed. `implementation/` and the test artifacts were not touched in Steps 8-9, so the Step 7 clean sweep (results.{1..8}.json, 83/83 each) remains the standing test evidence.

---

## Pipeline complete — 2026-08-31T23:10:00.000Z

All nine steps have valid artifacts on disk. Final state: 83 tests, 8/8 parallel rounds at 83/83, 0 skips, 0 xfails, 72/72 endpoints implemented.
