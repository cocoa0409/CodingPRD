# Worklog — task_2344_consumer_repair_parts_self_service

## Step 1: Create task directory — 2026-09-01T22:16:49.346Z

Created `tasks/task_2344_consumer_repair_parts_self_service/` and `tasks/task_2344_consumer_repair_parts_self_service/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T00:45:43.453Z

All three artifacts are complete and lint-clean.

## Verdict block (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2344_consumer_repair_parts_self_service/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2344_consumer_repair_parts_self_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2344_consumer_repair_parts_self_service/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  1295

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

## SCAFFOLD.yaml (§1.0–§1.7)

`domain_name: consumer-repair-parts-self-service`, `api_prefix: /repair-program`, `difficulty_level: beyond_expert`.
Complexity profile: `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers = optimistic_concurrency / cascading_side_effects / dual_variant_calculation / version_pinning_on_approval.

Counts: **13 entities · 72 endpoints · 8 state machines · 2 concurrency rules · 15 calculations · 56 validations · 66 errors · 7 roles.** Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in this file (top keys verified).

## §1.8 — SCAFFOLD_DIFFICULTY_DESIGN.yaml

**9 rules / 20 instances**: dual_variant_calculation ×2, combinatorial_formula ×2, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair_validation_conflict ×2, boundary_precision_check ×3, cross_entity_state_dependency ×2, resource_temporal_overlap ×3, compensating_invariant ×2.

## §1.9 — SCAFFOLD_CORNER_DESIGN.yaml

**9 sections / 99 instances** (75 full recipes + 24 `excluded_because` stubs that defer to a named §1.8 instance):
entities 14 · state_machines 15 · calculations 23 · validations 17 · endpoints 6 · errors 8 · rbac 7 · cross_cutting_layers 7 · consistency_model 2.

All 119 instance names are unique across both design files.

## Coverage-audit notes

- **Error reachability:** all 66 codes in §1.6 now have a positive trigger. 11 were unreachable before the `errors` and `cross_cutting_layers` sections were added (mostly the not-found family and the stale-version pair); the not-found sweep covers 13 codes in one recipe using literal bogus UUIDs, which is lint-legal because a hardcoded UUID segment satisfies `path_matches_template`.
- `ERR_TRAINING_CREDIT_INSUFFICIENT` existed in §1.8 only as a negative assert (`${err2} != …`), so §1.9 adds an explicit positive trigger (provider credit balance spent, `required_cert_count 2 = ceil(8/4)`).
- **Reverse-reachability:** 8 endpoints were added to §1.5 during the audit so every §1.1 FK target is listable/readable from its parent.
- **Two scaffold self-consistency fixes** (beyond the earlier A–G): (H) the `ComplianceObligation → ATTESTED` precondition now requires `documentation_posture == CURRENT`, matching the §1.4 priority-90 guard, so STALE and MISSING both block attestation; (I) `PartsOrder PENDING_DISCLOSURE → CONFIRMED` no longer re-pins the manual revision — it keeps the revision the `EligibilityAssessment` pinned, which is what `version_pinning_on_approval` and the priority-86 acknowledgment check require.
- **Lint iteration:** the first run reported 17 `(d) capture JSONPath unresolvable` violations. Root causes: paginated list endpoints (`output: X[]`) cannot capture `$.data.total_count` / `$.data.has_more` — those pagination fields live outside `data` per the §1.0 envelope, so they became `$.total_count` / `$.has_more` (15 captures); and two captures used a non-existent field `attested_at` instead of the declared `last_attested_at`. After those repairs the lint is clean with no other class of violation.

## Step 3: Copy shared files — 2026-09-02T00:45:43.453Z

Copied `INSTRUCTION.md` → `tasks/task_2344_consumer_repair_parts_self_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T01:01:24.581Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2344_consumer_repair_parts_self_service/workspace/PRD.md`.

**Size:** 440 lines.

**Sections written**

- `## 1. Introduction` — 3 paragraphs from the scaffold scenario (right-to-repair mandate pressure vs. safety duty), closing on the two dominating properties (non-local cascades, conserved ledgers) and the `/repair-program` mount.
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 Actors/Identity Headers/RBAC; 2.2 API Response Structure (pasted byte-identically from `section-2.2-response-structure.md`, verified by exact substring match); 2.3 Pagination and Collection Filters; 2.4 Common Resource Properties, Timestamps and the Logical Clock; 2.5 Money, Counts, Ratios and Rounding; 2.6 Optimistic Concurrency Control on Stale Parent Versions; 2.7 Cascade Discipline and Hierarchical Consistency; 2.8 Path Resolution, Nesting and Ownership; 2.9 The Global Rejection Ladder; 2.10 The Two Conservation Invariants; 2.11 Segregation of Duties.
- `## 3. Business Logic & Workflows` — 9 subsections (product-model lifecycle; regional mandates/obligations/sweep; catalog + supersession + the 4-hop safety cascade; documentation under revision control + the 4-hop publish cascade; eligibility/warranty/risk; order assembly, pricing and confirmation; delivery/authentication/calibration/core return; provider programme; defective returns and long-tail forecasting).
- `## 4. Endpoint Definitions` — status-code intro paragraph plus 4-column table, **72 rows** (matches the scaffold's 72 endpoints exactly).
- `## 5. Error Code Catalogue` — 2-column table, **66 rows** (matches the scaffold's 66 errors exactly). Document ends here; no audit footer.

**Hard Contract 1 — Field-Name Coverage** (run twice, second pass re-derived the required set independently from the scaffold rather than from the cached `/tmp/req.json`):

```
Field coverage check:
- entities[].fields: 138 required, 138 present, 0 missing
- endpoints[].request_body: 95 required, 95 present, 0 missing
- endpoints[].query_params: 12 required, 12 present, 0 missing
Status: PASS
```
(The 12 figure is the distinct path/identifier parameter set; the 95 covers all body fields and query filters with the optional marker stripped. All 20 computed-read output keys — `swept_obligation_count`, `breached_obligation_ids`, `expired_assessment_ids`, `restricted_model_ids`, `cert_coverage_ratio`, `breach_count`, `calibration_failure_ratio`, `score`, `access_tier_band`, `variant`, `trailing_units`, `pipeline_units`, `base_monthly_units`, `obsolescence_band`, `band_multiplier`, `projected_units`, `safety_stock_pct`, `mandated_buffer_units`, `recommended_stock_units`, `current_utc` — are also named in backticks.)

**Hard Contract 2 — Rule Coverage:**
```
Rule coverage check:
- validations: 56 of 56 expressed, all with priority position stated (via the §2.9 ordered ladder plus per-workflow conditions in §3)
- concurrency_rules: 2 of 2 expressed with parent, OCC field, write endpoint, error and 412 status
- state_machines: 41 of 41 transitions expressed across 8 machines; every state string present
- calculations: 15 of 15 expressed; all named constants' values present in prose
- validations conditions: all thresholds, enum sets and applies_to scopes expressed
- endpoints side_effects: all cascade hops, ledger movements and rollups expressed
- entities fields: all enums, ranges, defaults and formats expressed
- sibling-branch symmetry: both credit-decision branches, both review-decision branches, all 4 authorization decisions, all core-settlement outcomes stated
Status: PASS
```

**Hard Contract 3 — §3 Path Purity:**
```
Path purity check (section 3 only):
- backtick tokens scanned: 1152
- tokens starting with "/": 0
- bare HTTP-method tokens: 0
- method+path combined: 0
- raw "/repair-program" occurrences outside backticks: 0
Status: PASS
```

**Coverage / Zero-Silence notes**

- No fuzzy quantifiers survive; no `==`/`>=`/`min()`/`ceil()`/`round()`/`AND`/`OR`/`IN` pseudocode leaked into prose (scripted scan clean). Both OCC rules are framed purely in stale-version terms — no "simultaneously", "first-writer-wins", "race", or "arriving together" phrasing anywhere.
- Both documented priority-conflict pairs are stated explicitly in §2.9 (restricted-part interlock masks expired-assessment; provider-not-accepting-certs masks insufficient-training-credit), as is the single exemption where a second core-return booking bypasses the undefined-trigger refusal and falls through to `ERR_CORE_LEDGER_INVARIANT`.
- One scaffold/spec discrepancy resolved in favour of the spec: validation priority 5's rule text names the role header "X-Role", but §2.1 documents it as `X-User-Role` as the generator spec mandates.
- One scaffold internal tension made explicit rather than silently dropped: line `authentication_status`/`calibration_status` are described as *captured* from the part's `requires_authentication`/`requires_calibration` flags at line append, and *activated* (to `PENDING_AUTHENTICATION` with a minted `pairing_token`, and to `CALIBRATION_REQUIRED`) at delivery — which reconciles the endpoint side-effect text with the state machine.
- The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T03:09:59.634Z

(Note: this subagent was interrupted once by a transport-level API error and was resumed with its context intact; the summary below is its final report.)

The suite is complete and audited.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2344_consumer_repair_parts_self_service/`)

- `test_helpers/`: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
- `test_suite/`: `conftest.py` plus 19 test files, `test_01_order_pricing_and_forecast.py` → `test_19_concurrency_pinning_and_immediacy.py` (8163 lines total)

Final file added this session: `test_suite/test_19_concurrency_pinning_and_immediacy.py` — 5 tests closing the last two queue-B sections (3 `cross_cutting_layers`: both OCC guards with their prescribed re-read recovery, and the order that keeps its pinned revision across a guide publication; 2 `consistency_model`: order money current in the append's own response, parent posture rollup current in the response that created the obligation).

**Test counts**

- Queue A (Difficulty): 42 tests over 19 of 20 non-stub instances, 9 rules — files `test_01`–`test_06`.
- Queue B (Corner): 75 tests over 75 of 75 non-stub instances (24 stub instances marked `excluded_because.difficulty_instance` correctly emitted nothing) — files `test_07`–`test_19`. Per section: entities 14, state_machines 12, calculations 14, validations 14, endpoints 6, errors 3, rbac 7, cross_cutting_layers 3, consistency_model 2.
- Total 117 tests, 94 distinct design tags (one per non-stub instance converted).

**Instances skipped** (1)

- `Difficulty/transitive_cascade/part_restriction_cascades_to_compatibility_assessment_and_order_hold` — fails the uniquely-derives condition. Its recipe uses one assessment that the order is created against, but PRD §3.6 line 220 says order creation "moves the assessment from `VALID` to `CONSUMED`", while the §3.4 line 184 cascade's third hop "finds every eligibility assessment still in `VALID`" and the fourth hop only touches "orders standing behind the assessments just revoked". The asserted `REVOKED_BY_SAFETY` / `BLOCKED_SAFETY_HOLD` outcomes are therefore contradicted, not derived, by the PRD for that setup. No placeholder, skip, or xfail was emitted. (One narrower omission also stands: in `test_16` the tool-scoped nested compatibility read assertion was dropped as not uniquely derivable, while the rest of that instance was converted.)

**Stage 2 / self-audit results**

- Citation audit: 117 tests, 0 problems — every double-quoted span survives a whitespace-normalised literal grep of `workspace/PRD.md`; every docstring ends with exactly one `Design:` line as its last line; no untagged or dual-tagged tests.
- Scaffold-tag audit against both yamls: 0 unresolvable tags, 0 tags pointing at stub instances, 0 uncovered non-stub queue-B instances.
- Fixed one tag typo found by the audit: `test_11` pointed at `Corner/calculations/pairing_override_frees_eligibility_while_warranty_reads_the_stored_class`; corrected to the verbatim instance name `..._the_stored_safety_class`.
- `python3 -m py_compile` clean on every file in `test_suite/` and `test_helpers/`; no `skip`/`xfail` markers anywhere; both `__pycache__` directories deleted.

The suite has never been executed — no implementation exists yet, and `workspace/implementation/` was not read.

## Step 6: Generate implementation — 2026-09-02T03:09:59.634Z

The implementation is complete, boots cleanly, and passes end-to-end verification.

## Files written

All under `workspace/implementation/` (~4,150 lines of Python across 22 modules).

**Launcher / infra**
- `start.sh` — guarded `pip install` then `exec python3 app.py` (honours `$PORT`, default 10000)
- `requirements.txt` — `flask>=2.0`
- `app.py` — app factory, registers 9 blueprints under `/repair-program`, error handlers for `ApiError` / 404 / 405 / `HTTPException` / uncaught `Exception`

**Foundation**
- `util.py` — logical-clock epoch `2026-08-01T00:00:00Z`, id/token/request-id generators, timestamp formatting (3 fractional digits + `Z`), `Fraction` helpers, round-half-up, date arithmetic with Feb-29 clamping
- `errors.py` — all 66 error codes with HTTP statuses grouped by the §2.9 ladder band
- `db.py` — 13 in-memory stores, logical clock, monotone `_seq`, per-request dirty set (`touch`/`setf`/`commit`/`rollback`) giving exactly one `version += 1` per mutated row per request
- `response.py`, `middleware.py`, `validation.py`, `serializers.py` — envelope + pagination, 7-role auth and scoping, typed body/query coercion, per-entity field projections

**Domain services** — `services/{compliance,pricing,eligibility,orders,providers,forecast}.py` (15 calculations, both declared variants each for provider score and demand forecast, largest-remainder core allocation, conservation-preserving core ledger)

**Routes** — `routes/{helpers,product_models,compliance,catalog,compatibilities,manual_revisions,assessments,orders,providers,returns}.py`

## Endpoint count

**Exactly 72**, matching PRD §4 one-for-one (verified against `app.url_map`).

## Verification performed

Four scripted scenarios over a live server (~140 calls, all expectations met after correcting my own test-side mistakes):

- Full happy path: profile → model → part → compatibility → publish → manual-revision lifecycle (create/submit/reject/resubmit/approve/publish) → provider onboarding (training → certs → authorize) → assessment → order → line → disclosure → ack → confirm → deliver → authenticate → calibrate → core-return → defective-return (receive/analysis/credit) — plus all 13 list endpoints, both nested collections, both derived reads, clock and sweep.
- Money math checked by hand: `core_deposit_cents` 40000 = 2 × 20000; `DAMAGED_SHELL` settlement 40000 × 0.7 = 28000 credited / 12000 forfeited; conservation identity `settled + forfeited + outstanding == committed` holds.
- State machines: calibration ladder FAILED → FAILED → ESCALATED → `ERR_CALIBRATION_ATTEMPTS_EXHAUSTED`; parallel dimensions roll the order up to `CLOSED` only when calibration passes; both OCC guards return `ERR_STALE_MODEL_VERSION` / `ERR_STALE_ORDER_VERSION` (412).
- Cascades: part-restrict hops 1–3, model-posture / obligation re-evaluation on publish, provider suspend/reinstate/revoke, cert-void auto-suspension with `CERT_COVERAGE_LOST`.
- Envelope/pagination: keys exactly `meta`/`response_type`/`data`; `api_request_id` matches `req_` + 20 uppercase alnum; list meta adds `limit`/`offset`/`total_count`/`has_more`; default sort is `created_at` ASC in insertion order.
- **Fresh-boot isolation** (the `--isolation per-test-server` requirement): three consecutive `start.sh` launches each came up clean with all 13 collections at `total_count: 0` and the clock back at `2026-08-01T00:00:00.000Z`. Nothing is seeded anywhere.

`__pycache__` directories removed; no temp or report files left behind.

## Defect fixed during verification

`services/orders.py` — `NO_CREDIT_ROOT_CAUSES` wrongly included `PROVIDER_INSTALL_ERROR`; PRD §3.9 blocks credit only for `CUSTOMER_MISUSE`. Corrected to `("CUSTOMER_MISUSE",)`.

## PRD ambiguities resolved

1. **Role header** — PRD says `X-User-Role`; SCAFFOLD validations mention `X-Role`. Primary is `X-User-Role`, `X-Role` accepted as an alias.
2. **Ladder precedence** — PRD §2.9's 11-band ladder overrides SCAFFOLD `validations[].priority` and per-endpoint prose ordering (e.g. at confirm, band-6 restricted-part precedes band-7 state and band-9 assessment-expired; at review-decision, band-5 self-review precedes the state gate; at credit-decision, band-6 calibration-incomplete precedes the state gate).
3. **HOP 4 of the safety cascade is unreachable by design** — the PRD and SCAFFOLD both filter HOP 3 to assessments `status == VALID`, but order creation always moves the assessment to `CONSUMED`, so no order can stand behind a just-revoked assessment. I implemented the literal spec (filter on `VALID`); the HOP-4 code is present and correct but only fires if an order ever references a still-`VALID` assessment. Worth flagging to whoever owns the PRD.
4. **Error-class split** — string-length violations (`model_code`/`sku` 3-32, `region_code` 2-8) → `ERR_INVALID_REQUEST`; numeric-bound violations → `ERR_INVALID_RANGE`; `limit`/`offset` non-integer → `ERR_INVALID_REQUEST`, out-of-range → `ERR_INVALID_RANGE`.
5. **Authorization decisions are not narrowed per-decision by role** — the prose calls SUSPEND/REVOKE "a `ComplianceOfficer` decision", but the §4 endpoint list authorises both `ProgramAdmin` and `ComplianceOfficer`, and SCAFFOLD's `actor:` field names only one representative role per transition (it names `ProgramAdmin` for AUTHORIZE). I gated at the endpoint level and let either role issue any of the four, since narrowing would invent an undeclared rejection.
6. **Lifecycle defaults** — a model created with `end_of_production_date` starts at `LEGACY_SUPPORT`; a predecessor part moves to `SUPERSEDED` when the successor is *published* (or immediately on supersession re-pointing), not at successor creation.
7. **Obligation creation reports `breach_count: 0`** even when the derived status is already breached.
8. **Compliance-profile booleans are optional** — `requires_public_manual` defaults false, `allows_pairing_restriction` defaults true.
9. **Acceptable ack scopes at confirm** — provider order → `{PROVIDER_MANAGED}`; consumer order with a COMPONENT/CONSUMABLE line → `{FULL_SELF_REPAIR}`; consumer tools/rentals-only → `{FULL_SELF_REPAIR, TOOL_RENTAL_ONLY}`. `ERR_DISCLOSURE_MISMATCH` at ack time reads "component line" literally as `part_class == COMPONENT`.
10. **Scope/ownership** — enforced on writes only, never on GETs. A null `provider_id` on a resource is not a violation; an unresolvable `RepairProviderTech` identity always is. `POST /parts-orders` enforces provider scope but not order ownership.
11. **Miscellaneous** — `restrict` with `safety_class == UNRESTRICTED` → `ERR_INVALID_REQUEST`; part `publish` checks `DRAFT` before the two `ERR_INVALID_RANGE` guards; `begin-training` with a grant below 2 → `ERR_INVALID_RANGE`; manual-revision publish with a regressing `effective_from` → `ERR_INVALID_STATE_TRANSITION`; self-review is forbidden for both APPROVE and REJECT (§2.11 is unqualified); the sweep narrows obligations by optional `model_id` but expires assessments globally; registering a compatibility row re-derives only the model's `documentation_posture`; `api_request_timestamp` reads the logical clock for consistency with `created_at`.

## Step 7: Run tests and iterate — 2026-09-02T07:11:17.386Z

Green. Final sweep: all 8 parallel rounds reported **117/117 passed**.

## Summary

**Iterations run:** 6 full 8-round parallel sweeps after the fix batch (plus 1 pre-fix diagnostic sweep and 1 partial serialized sweep). Sweeps 3–10 showed **zero assertion failures** in every round; the only non-passes were host-level infra artifacts (runner's own `lsof -ti:PORT` probe exceeding its hardcoded 5s subprocess timeout, and transport-level `RemoteDisconnected`/`ConnectionResetError`) caused by 250–300 unrelated `prd-bench-local-run` processes on the shared box (load avg 200 → 96). Those were confirmed non-deterministic (19 distinct tests hit 1–2 times each, randomly) and non-reproducible: 300 iterations of the exact request sequence from the one disconnect-affected test, against a dedicated server, produced 0 disconnects, 0 server tracebacks, 0 500s. The final sweep, once host load subsided, was fully clean 8/8.

**Tests deleted:** none. All 9 pre-fix failures cited verbatim PRD sentences and were uniquely derivable, so none met a STEP 1a/1b silence or collapse pattern.

**Fixes applied to `test_helpers/`:** none. No fixture, factory, or header helper was found to build a PRD-inconsistent precondition.

**Fixes applied to `implementation/`:**

1. `workspace/implementation/db.py` — `touch()` / `setf()` / `commit()` / `rollback()`, plus `Store.add` and new `_snapshots()`/`_inserts()` bookkeeping. The version bump used to run in `commit()`, which `envelope()` calls *after* the route has already serialized the row, so a mutating response reported the pre-mutation `version`/`updated_at`. The bump is now eager (at first `touch`), and `rollback()` restores a per-row snapshot and removes rows inserted during the request, so a refusal still changes nothing. Required by PRD §2.4: `version` "increments by one on every mutation — including mutations the server performs on its own initiative as part of a cascade, and including mutations that only change a computed field." Fixed 3 tests (order money current in the append response, parent rollup current in the child-create response, version frozen after a refused second publish).
2. `workspace/implementation/routes/compliance.py` — `create_obligation()`: removed the explicit `row["breach_count"] = 0` override that ran *after* `evaluate_obligation()`. Required by PRD §3.2: "Every evaluation that lands on either breached value increments `breach_count` by one." A creation-time derivation that already lands on `BREACHED_*` must count. Fixed 5 tests; the `breach_count == 0` assertions elsewhere remain correct because those obligations derive to `OPEN`/`AT_RISK`.
3. `workspace/implementation/routes/providers.py` — `compliance_score()`: added `check_provider_scope(provider["id"])` after referential resolution (ladder band 3 before band 5). Required by PRD §2.1: "Ownership checks on any provider-scoped resource … A technician whose user id resolves to a different provider, or resolves to no provider at all, is rejected with `ERR_PROVIDER_SCOPE_VIOLATION` (403)" — unqualified as to reads vs writes. Verified this is the only TECH-header provider-scoped read in the suite, so no regression. Fixed 1 test.
4. `workspace/implementation/services/compliance.py`, `routes/manual_revisions.py`, `routes/providers.py` (4 sites) — converted direct `row[field] = …; touch(row)` increments to `setf(...)` so the rollback snapshot is taken before the field changes. Supporting change for fix 1; no behavior change on success paths.

Storage remains in-memory dicts only — no seeding, no file/SQLite/`/tmp` persistence (verified by grep). Run artifacts (`results.*.json`, `__pycache__`) removed.

## Step 8: Finalize PRD — 2026-09-02T07:21:58.664Z

(Orchestrator note: an independent confirming 8-round parallel sweep run alongside this step regenerated `workspace/implementation/results.{1..8}.json` — all 8 rounds 117/117.)

`workspace/PRD_FINALIZED.md` is written.

## Line counts
- PRD.md: 440 lines / 111,513 chars
- PRD_FINALIZED.md: 440 lines / 113,020 chars
- Line delta: 0 (+0.00%); character delta: +1,507 (+1.35%) — three inline sentence additions, no new sections.

## Changes
- **§2.1 (Actors/RBAC, line 21) — insert — pinned the reach of the `ERR_PROVIDER_SCOPE_VIOLATION` check: it guards every technician-performable provider-scoped write plus the provider compliance-score read, while plain single-resource and collection reads apply no provider scoping — `routes/providers.py:150`, `middleware.py:95-103`.**
- **§2.4 (Common resource properties, line 84) — insert — pinned (a) at most one `version`/`updated_at` move per row per request, and `version` staying at 1 for a row the same request created and then derived; (b) a write's own response body reporting the post-write `version`/`updated_at`/derived fields; (c) a refused request restoring altered rows and discarding inserted rows — `db.py:88-108` (`touch`), `db.py:120-126` (`base_row`/`_fresh`), `db.py:129-149` (`commit`/`rollback`), `response.py:23-25,38-40`.**
- **§3.2 (Obligation creation, line 162) — insert — an obligation whose creation-time derivation lands on `BREACHED_PARTS`/`BREACHED_DOCUMENTATION` is created with `breach_count` at one (previously the PRD's "starts at zero" contradicted the impl) — `routes/compliance.py:85-90`, `services/compliance.py:171-173`.**

No edit was made for step_7_diff item 4 (`setf` conversions): pure supporting refactor with no success-path behavior change; its only observable consequence (refusals restore pre-change values) is covered by the §2.4 sentence above.

## Per-edit pre-edit search log

**Edit 1 — §2.1 provider scope**
- (a) Subject: where `check_provider_scope` (`ERR_PROVIDER_SCOPE_VIOLATION`) fires — reads vs writes, and which resources.
- (b) Paths enumerated: `grep -rn "check_provider_scope|check_order_ownership|check_assessment_ownership|_caller_scope"` over all of `implementation/`. Callsites read: `middleware.py:95-103` (no-op for non-tech roles; rejects unresolved tech even when the resource's `provider_id` is null), `routes/assessments.py:47` (create), `routes/orders.py:49-51` (`_caller_scope`), `:105` (create), `:189` lines, `:278` request-disclosure, `:331` acknowledgments, `:400` confirm, `:500` cancel, `:561` authenticate, `:590` calibrate, `routes/returns.py:43-47` (defective-return filing), `routes/providers.py:150` (compliance-score read), `:202` (cert filing). Confirmed *no* check on `read_provider`/`list_providers`/`list_provider_certs`/`read_cert`/`list_certs` or any order/line/assessment GET; confirmed every remaining unchecked write (`begin-training`, `authorization-decision`, `void`, `deliver`, `core-returns`, return `receive`/`analysis`/`credit-decision`) is not authorized for `RepairProviderTech` at all, so the check would be unobservable there.
- (c) Adjustment: enumerated the tech-callable writes explicitly instead of writing "all writes" (which would have implied checks on admin-only provider writes), and stated the reads carve-out as "no provider scoping at all" (not "only own provider") because unchecked reads succeed even for a technician who resolves to no provider. Did not touch the neighbouring `ERR_ORDER_NOT_OWNED` sentence (impl also skips ownership on reads, and `check_assessment_ownership` is dead code — out of this diff's scope).

**Edit 2 — §2.4 version/updated_at and refusal atomicity**
- (a) Subject: the version/`updated_at` bump bookkeeping in `db.touch()`, its interaction with freshly created rows, response serialization order, and `rollback()`.
- (b) Paths enumerated: `db.py` in full (`touch`, `setf`, `base_row`/`_fresh`, `_snapshots`, `_inserts`, `Store.add`, `commit`, `rollback`); `response.py` (`envelope` calls `db.commit()`, `error_response` calls `db.rollback()`); `grep -rn '"version"'` across `implementation/` (only `db.py:104-105`, `db.py:124`, plus the two read-only comparisons in `routes/manual_revisions.py:47` and `routes/orders.py:186` — no other bump site); `grep -rn "_json(" routes/*.py` confirming every serializer call is in a `return`, i.e. serialization always follows all mutations; cascade fan-outs that re-touch the same row (`services/compliance.py` `rollup_documentation_posture`/`evaluate_obligation`/`rollup_model_posture`/`reevaluate_model_obligations`, `routes/catalog.py:191`, `routes/manual_revisions.py:171-184`, `routes/product_models.py:106-142`, `routes/compliance.py:89-92,155-174`, `routes/orders.py` confirm/deliver/cancel/core-returns/calibrate); creation-then-derivation paths that keep `version` at 1 (`create_obligation`, `append_line` + `price_order`, `create_revision` + `refresh_revision_coverage`).
- (c) Adjustments: (i) wrote "move **at most** once per request" rather than "once per changed field", because `evaluate_obligation(..., force_touch=True)` in the sweep and in end-of-production bumps an obligation whose fields did not change — a "only when a field changes" claim would have been a new mismatch; (ii) scoped the response-freshness claim to "the row it returns" (impl's line-append response echoes the priced *line*, not the order), rather than claiming cascaded rows are echoed; (iii) opened with "Where `updated_at` and `version` are carried" so the sentence is not read as applying to the versionless `DisclosureAcknowledgment` described immediately before.

**Edit 3 — §3.2 obligation creation `breach_count`**
- (a) Subject: every write of `breach_count` on a `ComplianceObligation`.
- (b) Paths enumerated: `grep -rn "breach_count"` — `routes/compliance.py:85` (initial 0 at creation, with the former post-derivation `= 0` override now removed), `services/compliance.py:171-173` (sole increment, inside `evaluate_obligation`), `serializers.py:53` (projection); all `evaluate_obligation` callers checked (`routes/compliance.py:90` create, `:155` sweep, `routes/product_models.py:106` end-production, `services/compliance.py:202-205` → `routes/catalog.py:191` part publish, `routes/manual_revisions.py:183` revision publish); verified nothing ever decrements or resets it (attest only sets status/verification), and that `services/providers.py:71-102` `breach_count` is a distinct defective-return figure, not this field.
- (c) Adjustment: added a trailing sentence rather than deleting "starts at zero", and conditioned it on the two breached statuses only, so obligations deriving to `OPEN`/`AT_RISK`/`CLOSED` at creation still read zero (matching `evaluate_obligation`'s branch guard).

## Step 9: Complete PRD — 2026-09-02T07:52:37.584Z

Done. `PRD_COMPLETED.md` is finished; the implementation walk is complete and three mechanical cross-checks (error catalogue, endpoint inventory, role columns) all come back clean.

## Metrics

| | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 440 | 113,020 |
| `workspace/PRD_COMPLETED.md` | 440 | 125,629 |
| delta | 0 | **+12,609** (net +12,515 by content diff) |

46 of 440 lines differ; no line was added or removed, no section added. **89 logical changes: 71 ambiguity-pins, 18 mismatch-revisions.**

## Changes

§2.1 Actors/RBAC
- §2.1 — insert — ambiguity — `X-Role` is consulted as a fallback when `X-User-Role` is absent — `middleware.py:30`
- §2.1 — revise — **mismatch** — ownership is compared on the order's `customer_user_id` only; an assessment's `requester_user_id` is never compared, and the acknowledgment comparison applies to *both* buyer roles — `middleware.py:88` (dead), `routes/orders.py:330`
- §2.1 — insert — ambiguity — technician→provider resolution takes the earliest matching certification by `created_at`/sequence whatever its status or window — `middleware.py:69`
- §2.1 — insert — ambiguity — a null `provider_id` on the resource still requires resolution but skips the comparison — `middleware.py:95`

§2.2–§2.4 envelope, pagination, common properties
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, so it repeats until the clock moves — `response.py:17`
- §2.3 — insert — ambiguity — out-of-band `limit`/negative `offset` → `ERR_INVALID_RANGE`; non-integer → `ERR_INVALID_REQUEST` — `validation.py:100`
- §2.3 — insert — ambiguity — rows sharing a `created_at` are ordered by insertion sequence — `db.py:156`
- §2.3 — insert — ambiguity — `total_count` counts the filtered set pre-page; `has_more` is `offset + len(page) < total` — `response.py:85`
- §2.3 — insert — ambiguity — filter semantics: empty ignored, exact string equality, boolean token set, `as_of_date` parse + half-open window — `routes/helpers.py:124`
- §2.4 — insert — ambiguity — assigning a field its existing value is not a mutation and does not move `version`/`updated_at` — `db.py:111`

§3.1 Product models
- §3.1 — insert — ambiguity — `model_code` length violation is `ERR_INVALID_REQUEST`, not a range error — `routes/product_models.py`
- §3.1 — insert — ambiguity — the date comparison precedes the duplicate-code check — `routes/product_models.py`
- §3.1 — insert — ambiguity — end-production from any other `support_state` → `ERR_INVALID_STATE_TRANSITION` — `product_models.py:95`
- §3.1 — insert — ambiguity — the band-2 date refusal precedes that state check — `product_models.py:92`
- §3.1 — revise — **mismatch** — every obligation of the model bumps `version` whether or not its status moved (`force_touch=True`) — `product_models.py:106`
- §3.1 — insert — ambiguity — end-support date check precedes the state check and is skipped when `end_of_production_date` is null — `product_models.py:119`

§3.2 Mandates, obligations, sweep
- §3.2 — insert — ambiguity — profile validation bands, `requires_public_manual`/`allows_pairing_restriction` defaults, mandatory fee — `routes/compliance.py:36`
- §3.2 — insert — ambiguity — `documentation_verified` is optional and defaults to false — `compliance.py:101`
- §3.2 — insert — ambiguity — `ATTESTED`/`CLOSED` are inadmissible sources, and that band-7 refusal masks `ERR_ATTESTATION_UNSUPPORTED` — `compliance.py:105`
- §3.2 — insert — ambiguity — a sweep naming an unknown `model_id` → `ERR_MODEL_NOT_FOUND` — `compliance.py:148`
- §3.2 — insert — ambiguity — the assessment-expiry pass is global, never narrowed by `model_id` — `compliance.py:163`
- §3.2 — insert — ambiguity — the sweep bumps `version` on every obligation in scope even when nothing changed — `compliance.py:155`
- §3.2 — insert — ambiguity — definitions of the four sweep response fields — `compliance.py:176`

§3.3 Catalog, supersession, safety cascade
- §3.3 — insert — ambiguity — registration validation bands; `concurrent_rental_capacity` 0 is admissible at registration — `catalog.py:71`
- §3.3 — insert — ambiguity — the duplicate-sku check and predecessor lookup precede the graph checks — `catalog.py:69`
- §3.3 — insert — ambiguity — the `DRAFT` precondition on publish masks both stored-column range checks — `catalog.py:165`
- §3.3 — revise — **mismatch** — obligations are re-evaluated for *every* in-window model, not only those whose posture moved — `catalog.py:190`
- §3.3 — insert — ambiguity — a predecessor in any status other than `PUBLISHED` is left untouched — `catalog.py:62`
- §3.3 — revise — **mismatch** — version-bump split: part and every reached model unconditionally, obligations only on real change — `catalog.py:191`, `services/compliance.py:174`
- §3.3 — revise — **mismatch** — `supersedes_part_id` is mandatory on re-point — `catalog.py:201`
- §3.3 — insert — ambiguity — `supersession_note` is accepted but recorded nowhere — `catalog.py:202`
- §3.3 — revise — **mismatch** — re-point carries no state precondition on the part being re-pointed — `catalog.py:209`
- §3.3 — insert — ambiguity — restricting a part in any other status → `ERR_INVALID_STATE_TRANSITION` — `catalog.py:216`
- §3.3 — insert — ambiguity — an `UNRESTRICTED` replacement class → `ERR_INVALID_REQUEST`, before the part is resolved — `catalog.py:218`
- §3.3 — insert — ambiguity — `restriction_reason` is optional and stored null — `catalog.py:219`
- §3.3 — insert — ambiguity — compatibility flag defaults; `effective_from` mandatory, `effective_until` optional — `routes/compatibilities.py:22`
- §3.3 — insert — ambiguity — `install_minutes` 1–600 refused before any identifier is resolved — `compatibilities.py:45`

§3.4 Documentation
- §3.4 — insert — ambiguity — `covered_part_skus` is mandatory but may legitimately be empty at create — `manual_revisions.py:41`
- §3.4 — insert — ambiguity — negative `safety_warning_count` → `ERR_INVALID_RANGE` — `manual_revisions.py:45`
- §3.4 — revise — **mismatch** — the self-review guard fires on approval *and* rejection, before the `IN_REVIEW` state check — `manual_revisions.py:115`
- §3.4 — insert — ambiguity — `review_note` is not persisted — `manual_revisions.py:110`
- §3.4 — insert — ambiguity — publishing from any status other than `APPROVED` → `ERR_INVALID_STATE_TRANSITION` — `manual_revisions.py:153`
- §3.4 — insert — ambiguity — a backdated `effective_from` is a state refusal evaluated before the warnings check — `manual_revisions.py:159`
- §3.4 — revise — **mismatch** — publication cascade bumps the model unconditionally but an obligation only on real change — `manual_revisions.py:183`
- §3.4 — insert — ambiguity — the `MISSING` branch nulls the disassembly number, still refreshes the safety-sheet number, and computes no coverage gap — `services/compliance.py:77`

§3.5 Eligibility
- §3.5 — insert — ambiguity — `provider_id` required for `AUTHORIZED_PROVIDER`; a consumer-supplied one is stored, not rejected — `routes/assessments.py:34`
- §3.5 — revise — **mismatch** — `tool_rental_part_id` is emitted only by the tool-rental branch, so it is null on `ELIGIBLE` and all blocked decisions — `services/eligibility.py:31`
- §3.5 — insert — ambiguity — the risk index reads the stored `safety_class`, not the pairing-override effective value — `services/eligibility.py`
- §3.5 — insert — ambiguity — the install weight is the selected compatibility row's `install_minutes` ÷ 120 — `services/eligibility.py`

§3.6 Orders
- §3.6 — insert — ambiguity — `provider_id` rules on order creation — `routes/orders.py:87`
- §3.6 — insert — ambiguity — the rental date range is compared only when both bounds are present — `routes/orders.py:82`
- §3.6 — revise — **mismatch** — `pinned_manual_revision_number` is derived from the pinned revision row; the order's `region_code` need not equal the assessment's — `orders.py:122`
- §3.6 — insert — ambiguity — appending requires the order still be in `DRAFT` — `orders.py:192`
- §3.6 — insert — ambiguity — `quantity` above 500 is also `ERR_INVALID_RANGE` — `orders.py:175`
- §3.6 — insert — ambiguity — a null `concurrent_rental_capacity` counts as zero for collision — `services/orders.py`
- §3.6 — insert — ambiguity — acknowledgment requires `PENDING_DISCLOSURE` — `orders.py:334`
- §3.6 — revise — **mismatch** — the `TOOL_RENTAL_ONLY` mismatch check tests `COMPONENT` only; a `CONSUMABLE` line does not trip it — `orders.py:301`
- §3.6 — revise — **mismatch** — at confirmation `COMPONENT` *or* `CONSUMABLE` narrows the acceptable scope to `FULL_SELF_REPAIR` alone; `PROVIDER_MANAGED` is the sole provider-order scope — `orders.py:309`
- §3.6 — insert — ambiguity — `cancellation_reason` optional, stored null when omitted — `orders.py:498`

§3.7 Delivery, calibration, core return
- §3.7 — insert — ambiguity — delivering from any other state → `ERR_INVALID_STATE_TRANSITION` — `orders.py:474`
- §3.7 — insert — ambiguity — `delivered_at` is stored as given, never compared to the clock or `confirmed_at` — `orders.py:470`
- §3.7 — insert — ambiguity — only `CALIBRATION_REQUIRED`/`CALIBRATION_FAILED` are admissible calibration sources — `orders.py:605`
- §3.7 — insert — ambiguity — core-receipt mandatory fields — `orders.py:524`
- §3.7 — insert — ambiguity — a `NOT_REQUIRED` core dimension is a state refusal; `DELIVERED` is asserted only for an order in `PENDING_CORE` — `orders.py:529`
- §3.7 — insert — ambiguity — `ERR_CORE_RECEIPT_BEFORE_CONFIRM` sits in band 9 ahead of the conservation refusal — `orders.py:521`
- §3.7 — revise — **mismatch** — zero graded credit yields `CORE_FORFEITED`; `core_days_late` is recorded on both outcomes — `services/orders.py:127`
- §3.7 — insert — ambiguity — multi-part core credit is split largest-remainder, ties by ascending part id — `services/orders.py:84`

§3.8 Provider programme
- §3.8 — insert — ambiguity — `technician_count` 1–500 checked before the region profile is resolved — `providers.py:39`
- §3.8 — revise — **mismatch** — the training grant minimum is **two**, with no upper bound, checked before the provider is resolved — `providers.py:79`
- §3.8 — insert — ambiguity — begin-training requires `APPLIED` — `providers.py:82`
- §3.8 — insert — ambiguity — `void_reason` optional — `providers.py:249`
- §3.8 — insert — ambiguity — the non-`ACTIVE` source refusal precedes the revoked-provider guard — `providers.py:252`
- §3.8 — revise — **mismatch** — nothing ever writes cert `EXPIRED`; `active_cert_count` is derived per read and counts lapsed `ACTIVE` rows — `serializers.py:194`
- §3.8 — revise — **mismatch** — both authorised roles may render any of the four decisions; no per-decision narrowing — `providers.py:96`
- §3.8 — insert — ambiguity — `decision_reason` optional — `providers.py:100`
- §3.8 — insert — ambiguity — the source-state check runs first of the decision's own checks — `providers.py:113`
- §3.8 — insert — ambiguity — `suspension_reason` is taken from the body's `decision_reason`, left null when absent — `providers.py:129`
- §3.8 — insert — ambiguity — revoke's four admissible sources; it leaves `suspension_reason` untouched — `providers.py:111`
- §3.8 — insert — ambiguity — the compliance-score payload carries `provider_id` — `providers.py:152`
- §3.8 — insert — ambiguity — `variant` default and validation — `providers.py:146`

§3.9 Returns, analysis, forecasting
- §3.9 — insert — ambiguity — case `quantity` >= 1 with no upper bound beyond conservation — `returns.py:41`
- §3.9 — revise — **mismatch** — case filing asserts nothing about the parent order's `fulfillment_status` — `returns.py:35`
- §3.9 — insert — ambiguity — `received_at` stored as given, never compared — `returns.py:94`
- §3.9 — insert — ambiguity — `root_cause_code`/`defect_confirmed` mandatory — `returns.py:113`
- §3.9 — insert — ambiguity — `analysis_note` accepted but not persisted — `returns.py:115`
- §3.9 — insert — ambiguity — credit-decision accepts an optional `decision_note` that is not persisted — `returns.py:134`
- §3.9 — revise — **mismatch** — forecast inputs are **query parameters** on the read, not a body — `catalog.py:274`
- §3.9 — insert — ambiguity — forecast validation split (`ERR_INVALID_RANGE` vs `ERR_INVALID_REQUEST`) and `variant` default `TRAILING_ONLY` — `catalog.py:275`
- §3.9 — insert — ambiguity — the response echoes `part_id`, `model_id`, `horizon_months` — `catalog.py:283`

Deliberately left unchanged: the §3 prose that enumerates checks in a different order than the code executes them (confirm, credit-decision, calibrate, authenticate, request-disclosure, append-line) — §2.9's 11-band ladder already pins the true order, so differing enumeration order in §3 is not a mismatch.
