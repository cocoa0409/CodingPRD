# Worklog — task_2572_age_restricted_delivery_verification

## Step 1: Create task directory — 2026-09-03T13:17:48.574Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2572_age_restricted_delivery_verification` and its `workspace/` subdirectory. Index and path were pre-assigned by the orchestration prompt (scenario 2572); no scan of `./tasks/` for index allocation was performed, per instruction, because up to 32 pipelines run concurrently on this host.

## Step 2: Generate scaffold — 2026-09-03T14:52:26.349Z

All three scaffold artifacts are complete, parse cleanly, and pass the scaffold linter.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2572_age_restricted_delivery_verification/`)
- `SCAFFOLD.yaml` — 3162 lines / 157 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2210 lines / 144 KB (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5675 lines / 335 KB (single key `scaffold_corner_design`)

**SCAFFOLD.yaml (§1.0–§1.7)** — `domain_name: age-restricted-delivery-verification`, `api_prefix: ""`, profile `compliance_audit` / `posture_driven_gating`, topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint`, difficulty `beyond_expert`. Contents: **15 entities**, **9 state machines** (Order carries two independent dimensions), **2 concurrency rules** (§1.2.1), **8 calculations** (2 dual-variant: order exposure provisional/final, partner risk ROLLING_90D/LIFETIME_WEIGHTED), **20 ordered validation tiers**, **65 endpoints**, **60 errors**, **6 roles** (PlatformAdmin, Customer, PartnerManager, Courier, ComplianceOfficer, SecretShopperAuditor).

**§1.8 difficulty design** — 9 rules × 2 instances = **18 instances**: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

**§1.9 corner design** — **91 instances** across 9 sections (79 full recipes + 12 `excluded_because` stubs citing the §1.8 instance that already covers the corner): entities 12, state_machines 13 (9+4), calculations 12 (8+4), validations 13 (11+2), endpoints 8, errors 21 (17+4), rbac 6, cross_cutting_complexity_layers 5 (3+2), consistency_model 1.

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint` — 1175 §1.8+§1.9 calls conform to §1.5, all §1.1 FKs reverse-reachable.
- Endpoint coverage: **65/65** endpoints exercised by real structured calls (not just prose).
- Error coverage: **60/60** catalog codes referenced by at least one instance.
- Instance names: 109 total, zero duplicates across the two design files.
- Each file ends at a real structural boundary (last `assert:` list item / last `shared_operations` entry); all three re-parse with `yaml.safe_load`.

Two defects found and fixed during this final pass: a capture of `$.data.customer_version` off an `IdentityCheck` response (not a declared field — replaced with an arithmetic `${cust_v1} + 1` OCC literal plus an explicit parent-version-bump assertion), and a `CourierCertification.expires_at` literal computed from `training_completed_at` instead of `issued_at` (corrected to `2027-08-20T12:00:00Z`).

Orchestrator verification: all three files present, line counts as reported (3162 / 2210 / 5675).

## Step 3: Copy shared files — 2026-09-03T14:52:26.349Z

Copied `./INSTRUCTION.md` to `tasks/task_2572_age_restricted_delivery_verification/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T15:11:00.000Z

PRD complete at `/home/ubuntu/github/CodingPRD/tasks/task_2572_age_restricted_delivery_verification/workspace/PRD.md`.

**Size:** 446 lines / ~14,050 words. Written in 9 chunks (1 Write + 8 `cat >>` heredoc appends), so nothing was lost to an output cap. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling task directories were never opened.

**Section list**
- `# Age-Restricted Delivery Verification API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (fixed block verbatim, both sub-headings intact) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Clock and the Epoch Sweep · 2.6 Nested Path Resolution and Referential Integrity · 2.7 Validation Precedence · 2.8 Optimistic Concurrency on Parent Rows · 2.9 Precision, Rounding and the Conservation of Money · 2.10 Local Time Geometry, Effective Periods and Interval Occupation · 2.11 Cascade Discipline and Derived-Field Recomputation (incl. the terminal-state inventory)
- `## 3. Business Logic & Workflows` — 3.1 Regulatory Reference Data · 3.2 Customers, Age Attestation and Identity Pre-Verification · 3.3 Building an Order and the Order-Time Compliance Battery · 3.4 Clearance, Dispatch and the Delivery-Partner Posture Gate · 3.5 The Courier Workforce · 3.6 At the Door: Attempt, ID Check, Handover · 3.7 Refusal, Abort, and the Return Settlement Waterfall · 3.8 Secret-Shopper Testing and the Courier Compliance Score · 3.9 Violation Investigation, Licence Risk and Corrective Action
- `## 4. Endpoint Definitions` (65 rows, exactly 4 columns)
- `## 5. Error Code Catalogue` (60 rows, exactly 2 columns) — file ends here, no audit footer

**Coverage confirmation** (all verified mechanically against SCAFFOLD.yaml): 15/15 entities · 65/65 endpoint paths present and tabulated · 60/60 error codes present and tabulated · 8/8 state machines with 56/56 transitions in explicit `FROM → TO` arrow form and every terminal state declared · 8/8 calculations (both dual variants of exposure and of licence risk expressed separately with their divergence examples) · 20/20 validation priority tiers with error ids, HTTP statuses and applies_to scopes · 2/2 OCC rules · 6/6 roles.

**Contract 1 — Field-Name Coverage**: entities[].fields 151/151 · request_body 101/101 · query_params 63/63 · path_params 1/1 · computed-read identifiers 26/26 → PASS

**Contract 2 — Rule Coverage**: validations 20/20 · OCC rejections 2/2 · transitions 56/56 · calculations 8/8 · validation conditions 60/60 · side_effects 36 + applies_to 20 · entities 15/15 reconstructible · sibling-branch symmetry 12/12 → PASS

**Contract 3 — §3 Path Purity**: 1025 backtick tokens scanned, 0 slash-paths, 0 bare HTTP methods, 0 method+path tokens → PASS

**Last line of the file, verbatim:**
`| `ERR_WINDOW_UNIT_LIMIT_EXCEEDED` | 422 |`

One scaffold discrepancy flagged by the generator: `CourierCertification`'s transition list contains only `ACTIVE → REVOKED` and `SUSPENDED → REVOKED`, while `ERR_INVALID_CERTIFICATION_STATE`'s condition says only an already-`REVOKED` row refuses revocation (implying `EXPIRED → REVOKED` is legal). The PRD follows the error condition and documents revocation as admissible from `ACTIVE`, `EXPIRED` or `SUSPENDED`, naming all three arrows.

**Orchestrator truncation check (per the known doc-generator failure mode):** `wc -l` = 446; `tail -25` shows the error catalogue running to a complete final row; `grep -c '^| `ERR_'` = 60 rows, matching the scaffold's 60-code catalogue; the last section header is `## 5. Error Code Catalogue` at line 381. The file ends at a real section boundary, not mid-sentence. No regeneration needed.

## Step 5+6 launch note — 2026-09-03T15:22:00.000Z

Orchestrator deviation, recorded for honesty: the skill requires Steps 5 and 6 be launched in a SINGLE assistant message so the impl generator starts before `test_suite/` exists (physical isolation). They were instead launched in two adjacent messages seconds apart. Mitigation applied: the Step 6 prompt carried an ABSOLUTE HARD CONSTRAINT forbidding any read/list/glob/grep of `test_helpers/`, `test_suite/`, both `SCAFFOLD_*_DESIGN.yaml`, and all sibling task dirs. Step 6's returned summary explicitly confirms test blindness was maintained (only SKILL.md, INSTRUCTION.md, SCAFFOLD.yaml, PRD.md were read), and `test_suite/` was still empty at the time Step 6 started writing.

## Step 6: Generate implementation — 2026-09-03T15:47:00.000Z

Implementation complete and verified.

## Files written (3,909 lines total)

Root: `/home/ubuntu/github/CodingPRD/tasks/task_2572_age_restricted_delivery_verification/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `exec python3 app.py`, guarded pip install (only when flask missing), `PORT` env |
| `requirements.txt` | 1 | `flask>=2.0.0` |
| `app.py` | 61 | app factory, 6 blueprints, `strict_slashes=False`, ApiError/HTTPException/Exception handlers |
| `db.py` | 190 | 15 in-memory dicts, all domain constants, logical clock, `new_row`, `sort_key`, `touch` |
| `errors.py` | 149 | `ApiError` + all 60 codes → HTTP status + default messages |
| `util.py` | 136 | `req_` ids, 3-fraction-digit ISO formatting, ROUND_HALF_UP `rhu`, local-minute/local-date, half-open `in_window`, `completed_years` |
| `response.py` | 127 | meta/response_type/data envelope, Decimal→float at the edge, pagination |
| `middleware.py` | 98 | `auth` (401 before 403, both before resource load), scope checks, segregation of duties, `fetch` 404 map |
| `validate.py` | 207 | tier-7 shape validators |
| `services/calc.py` | 230 | policy resolution, double-rounded exposure, identity confidence, permissibility, window geometry |
| `services/battery.py` | 162 | the submit-time tier ladder (45 → 50 → 56 → 60 → 70), non-mutating fact bundle |
| `services/parties.py` | 405 | partner risk (both variants), posture re-derivation + order-hold cascade, courier score/gates, case opening, settlement waterfall |
| `services/sweep.py` | 73 | 3-step epoch sweep |
| `routes/reference.py` | 248 | clock, jurisdictions, restriction policies, products |
| `routes/customers.py` | 185 | customers, attestation, identity checks (OCC) |
| `routes/partners.py` | 307 | partners, risk-assessment read model, couriers, certifications |
| `routes/orders.py` | 382 | orders, lines, submit, compliance-evaluation, clearance, dispatch, return-settlement |
| `routes/attempts.py` | 435 | attempts, id-check, handover, refuse, captures |
| `routes/compliance.py` | 503 | shopper tests, violation cases, corrective action plans |
| `routes/__init__.py`, `services/__init__.py` | 0, 0 | packages |

Storage is pure Python dicts; nothing is seeded, no disk persistence, `__pycache__` removed.

## Verification
- `python3 -m compileall -q` → **COMPILE OK**
- **65/65** endpoints registered (Flask url_map count matches the 65 declared)
- **60/60** error codes wired — zero unreferenced, zero referenced-but-undeclared

## Smoke test (port 18572, launched via `bash start.sh`, killed by captured PID 3171515 then `fuser -k 18572/tcp`; port confirmed free)
A ~45-call walkthrough covering the full happy path plus error precedence:
- Auth: no headers → 401 `ERR_MISSING_AUTH_HEADER`; Courier on admin route → 403 `ERR_UNAUTHORIZED`; cross-principal attestation → 403 `ERR_FORBIDDEN_RESOURCE_SCOPE`
- Reference data: jurisdiction 201; bad code → `ERR_VALIDATION`; dup → `ERR_DUPLICATE_CODE`; policy 201 and `active_policy_count` 0→1 with jurisdiction version 1→2; shared-boundary date → 409 `ERR_POLICY_PERIOD_OVERLAP`; NONE product with units → `ERR_VALIDATION`
- Identity: identity check 201 with `confidence 0.9`, `expires_at` = created + 90d; replayed `expected_customer_version` → 412 `ERR_STALE_CUSTOMER_VERSION`; repeated source_type → 422 `ERR_INCONSISTENT_FIELDS`
- **Calculation check against the PRD worked example**: lines 3×1.50, 2×0.75, 1×0.05 at `unit_scale_factor` 1.15 produced `provisional_restricted_units = 6.97` (expected 6.97) and `charged_cents = 15800` (15200 items + 600 fee); route = `PREVERIFIED`; per-line `line_restricted_units` populated (5.18 on the first line); resubmit → 409 `ERR_INVALID_ORDER_STATE`
- Certification: score 50 → 422 `ERR_TRAINING_SCORE_TOO_LOW`; score 95 → 201, courier flips `UNCERTIFIED`→`CERTIFIED` and `dispatch_eligible` false→true
- Door side: `TRIBAL_ID` → `ERR_DOCUMENT_TYPE_NOT_ACCEPTABLE`; `scan_performed:false` → `ERR_SCAN_REQUIRED`; valid PASSPORT → `ID_VERIFIED`; handover before evidence → `ERR_CAPTURE_INCOMPLETE`; dup kind → `ERR_DUPLICATE_CAPTURE_KIND`; dup hash → `ERR_DUPLICATE_CODE`; handover → `HANDED_OVER`, order `DELIVERED`, `delivered_at` = attempt `started_at` verbatim, `final_restricted_units = 6.97`, `compliant_handover_count` 0→1
- Clock: advance → 200 with the three sweep counters; rewind → 409 `ERR_CLOCK_REWIND`; risk-assessment read model returns both variants and an empty `case_breakdown`

One result worth flagging as intended rather than a defect: the second attempt for the same courier returned `ERR_INVALID_ORDER_STATE` instead of `ERR_COURIER_SLOT_CONFLICT`, because the first attempt had already moved the order to `OUT_FOR_DELIVERY` and tier 10 (order state) legitimately precedes tier 18 (dwell conflict) in the ladder.

Test blindness was maintained throughout: only `SKILL.md`, `INSTRUCTION.md`, `SCAFFOLD.yaml` and `PRD.md` were read. `test_helpers/`, `test_suite/`, both `SCAFFOLD_*_DESIGN.yaml` files, the concurrent generator's partial output file, and all sibling task directories were never opened.

## Step 5: Generate unit tests — 2026-09-03T17:05:00.000Z

(Appended after Step 6's entry because worklog is append-only and Step 6's subagent finished first; Steps 5 and 6 ran concurrently.)

The suite is finished and fully verified.

## What landed

`test_helpers/` — 9 modules, 2,949 lines
`__init__.py` 75 · `api_client.py` 409 (65 endpoint methods) · `api_errors.py` 170 (57 codes + `HTTP_STATUS_CODES`) · `assertions.py` 311 · `constants.py` 384 · `factories.py` 497 · `fixtures.py` 682 (world builders) · `test_users.py` 91 (per-identity header makers) · `types.py` 330

`test_suite/` — `conftest.py` (53) + 18 test modules, 7,116 lines, **132 tests**
Queue A (57 tests): `test_01_exposure_and_quota_arithmetic` 346/6 · `test_02_partner_risk_variants` 303/6 · `test_03_return_settlement_waterfall` 164/6 · `test_04_order_state_dimensions` 221/6 · `test_05_corrective_action_plan_cycle` 194/5 · `test_06_cascades` 323/7 · `test_07_validation_precedence_conflicts` 354/9 · `test_08_cross_entity_gates` 299/6 · `test_09_interval_geometry` 248/6
Queue B (75 tests): `test_10_entity_lifecycles` 426/12 · `test_11_state_machine_transitions` 368/9 · `test_12_derived_calculations` 537/8 · `test_13_submit_gate_validations` 553/11 · `test_14_endpoint_round_trips` 724/8 · `test_15_error_catalogue` 1054/17 · `test_16_role_access_control` 506/6 · `test_17_concurrency_and_sweep_layers` 336/3 · `test_18_derived_field_immediacy` 160/1

## Design-index coverage

- Difficulty (§1.8): 18 live instances, **18/18 translated**, 0 stubs, no instance below the two-test floor.
- Corner (§1.9): 75 live instances, **75/75 translated**; the 16 `excluded_because:` stubs were deliberately not translated.
- Audit: `untagged/dual: []`, `bad tags: []`, `stub tags used: []`, 132 tagged tests = 132 collected tests (exactly one `Design:` line each).

## Verification (all green)

- `python3 -m compileall -q test_helpers test_suite` → clean
- `python3 -m pyflakes test_suite/*.py` → silent (exit 0)
- `PYTHONPATH=$PWD python3 -m pytest test_suite --collect-only -q` → **132 tests collected in 0.43s**, zero collection errors
- Reflective AST audit of every `f.*` / `fx.*` / `api.*` / `ApiErrorId.*` reference against the real modules → `BAD: []`
- Citation pass: 163 PRD quotes extracted from docstrings, whitespace-normalized and substring-matched against `workspace/PRD.md` → **0 misquotes**, and every quote now begins at a real sentence boundary (the two residual flags are quotes that open immediately after a `### 2.9.` / `### 3.2.` heading).

## Notable repairs and PRD-over-design divergences

Citation repairs this pass: one content error (`test_13` quoted PRD 2.6's body-FK list with a non-existent `ERR_POLICY_NOT_FOUND`; the test body only asserts `PRODUCT_NOT_FOUND`/`ORDER_NOT_FOUND`, so behaviour is unaffected), ten clause-boundary truncations extended to the PRD's real sentence end (`test_02`, `test_04`, `test_05`×2, `test_06`, `test_07`, `test_08`, `test_11`, `test_16`, `test_17`), and seven quotes that started mid-sentence extended back to the sentence's beginning (`test_01`×2, `test_05`×2, `test_06`, `test_08`, `test_13`). Earlier in the build, every file referenced `ApiErrorId.ERR_<NAME>` while the enum declares members unprefixed; that was repaired suite-wide and re-verified reflectively.

Where a design instance contradicted the PRD, the PRD won and the assertion was adjusted rather than weakened:
- `scenario_type` values `NO_ACCEPTABLE_ID` / `UNDERAGE_RECIPIENT` / `INTOXICATED_RECIPIENT` are not PRD 3.8 enum members → `NO_ID_PRESENTED` / `UNDERAGE_PRESENTER` / `INTOXICATION_CUES`.
- A new plan's `revision_round` asserted 0 (PRD 3.9), not the design's 1.
- At exactly 90 days the lifetime score asserted 36.00 — the PRD's own `1 − 0.1×floor(90/90)` weight of 0.90 — not the design's 40.00.
- The design's `refused_at` assertion was dropped: no such field exists in the PRD; `refusal_reason` and `observed_indicators` are asserted instead. Its `subtotal_cents`/`charged_total_cents` were corrected to `item_subtotal_cents`/`charged_cents`.
- One rbac instance staged its tier-3 identity check on an unrestricted order, where the age fork has no policy set to compare against; retargeted to a restricted world so `ID_VERIFIED` is uniquely derivable. The tier-3 point it exists to prove is unchanged.
- A handful of design-asserted figures with no unique PRD derivation were omitted rather than guessed (a `CLOSED_VERIFIED` case's `risk_contribution`, per-element `per_type_exposure` fields asserted by length only, an evaluated order's `version` asserted stable rather than 1).

Isolation held throughout: no sibling `task_*/` directory and nothing under `workspace/implementation/` was read.

## Step 7: Run tests and iterate — 2026-09-03T17:31:00.000Z

Fully green. Verified all 8 results files parse and each reports `total == 132`, matching the collected test count.

## Summary

**Iterations run:** 2

**Final sweep evidence** (8 concurrent rounds, `--isolation per-test-server`):

| Round | passed / total |
|---|---|
| 1 | 132 / 132 |
| 2 | 132 / 132 |
| 3 | 132 / 132 |
| 4 | 132 / 132 |
| 5 | 132 / 132 |
| 6 | 132 / 132 |
| 7 | 132 / 132 |
| 8 | 132 / 132 |

Iteration 1 failed 15 tests, identically in all 8 rounds — no flakiness anywhere in the sweep, so every failure was a real deterministic defect.

**Tests deleted:** none. All 15 failures survived STEP 1 (PRD verbatim coverage + unique derivability); they were two artifact bugs, not PRD-silence.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — the five product wrappers (`wine_product_payload`, `beer_product_payload`, `seltzer_product_payload`, `grocery_product_payload`, `cigar_product_payload`) each spliced `**overrides` alongside hardcoded `sku=`/`name=` keywords in the same `product_payload(...)` call, so any test overriding one of those five fields raised `TypeError: got multiple values for keyword argument`. Rewritten to merge the defaults dict with `overrides` via the existing `_merge` before splatting. This one fixture bug accounted for **13 of the 15 failures**, across `test_10`, `test_13`, `test_14`, `test_15`, `test_16` — matching the triage hint that a shared setup error points at test_helpers first.
- `test_helpers/assertions.py` — added `assert_instant_equal`, which compares two ISO 8601 UTC instants by value rather than by spelling (exported from `test_helpers/__init__.py`).

**Fix applied to `test_suite/`:**
- `test_06_cascades.py::test_05_a_second_failed_probe_rebuilds_the_score_to_fifty` asserted `probe["recorded_at"] == "2026-08-20T12:00:00Z"` against a server-stamped timestamp. PRD 3.8 verbatim covers the rule ("with `recorded_at` stamped from the logical clock"), and PRD 2.4 mandates "three fractional digits" on minted timestamps — but the PRD nowhere pins the *spelling* of `recorded_at` specifically, so the `.000` was a non-derivable detail bolted onto a covered rule (STEP 1c partial coverage). The covered assertion — the instant equals the clock — is preserved via `assert_instant_equal`; only the non-derivable formatting comparison was dropped. Not a weakening: the instant identity is still checked exactly.

**Fix applied to `implementation/`:**
- `workspace/implementation/routes/compliance.py`, `list_cases()` — PRD §4 states verbatim that `GET /violation-cases` "Lists violation cases filtered by partner, subject attempt, subject shopper test, state or origin", but the handler implemented only partner/state/severity/origin. The two missing subject filters (`delivery_attempt_id`, `secret_shopper_test_id`) were added, which is what `test_06_cascades.py::test_01` was exercising when it received 3 unfiltered cases instead of the 1 naming its attempt.

No implementation check was weakened, no assertion downgraded, no skip/xfail added, and storage remains in-memory dicts only.

**Orchestrator independent verification** (not taken on the subagent's word, per the known failure mode where a Step 7 agent reports a clean sweep with no artifacts on disk): all 8 `workspace/implementation/results.{1..8}.json` exist (~39.6 KB each, all timestamped 17:21), all 8 parse as JSON, and each reports `passed=132 total=132 failed=0`.

**Step 8 decision:** NOT skipped. Step 7 ran 2 iterations with 1 `implementation/` fix, 2 `test_helpers/` fixes and 1 `test_suite/` fix, so the skip condition (zero iterations beyond baseline) does not hold.

## Step 8: Finalize PRD — 2026-09-03T17:35:00.000Z

Done. `PRD_FINALIZED.md` written with three targeted edits.

## Line counts
- `PRD.md`: 446 lines — `PRD_FINALIZED.md`: 446 lines (0.00% line-count delta; 3 of 446 lines revised ≈ 0.67% of lines touched, all in-place prose insertions, no new sections).

## Changes
- **§2.4 Resource Identity, Timestamps and Revision Counters** — *insert* — added a uniform-rendering sentence: every instant the server itself mints (stamped from the logical clock, e.g. `updated_at`, `recorded_at`, `decided_at`, or derived by arithmetic on another instant) is written ISO 8601 UTC with exactly three fractional digits, while an instant supplied in a request body is stored/returned verbatim, as is any field copying such a value — `implementation/util.py:30` (`fmt_dt`), `implementation/db.py:139` (`now_str`), `implementation/routes/compliance.py:142`, `implementation/validate.py:119-127` (`req_dt` "echoed verbatim").
- **§3.9 (violation cases, line 287)** — *revise* — added `severity` to the case-listing filter enumeration and noted it matches the asserted `severity`, not `assessed_severity` — `implementation/routes/compliance.py:219,235-236`.
- **§4 endpoint table, `GET /violation-cases` (line 368)** — *revise* — "state, asserted severity or origin" — `implementation/routes/compliance.py:213-240`.

No PRD change for the `test_helpers/factories.py` wrapper bug (pure fixture `TypeError`, no behavioral claim) or for the two subject filters added to `list_cases()` (PRD §4 line 368 and §3.9 line 287 already named them verbatim — the impl was brought into line with the PRD, not vice versa).

## Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp rendering**
- (a) Subject: the spelling/format of every timestamp-valued field the API returns (triggered by the `recorded_at` spelling drop in `test_06_cascades.py::test_05`).
- (b) Enumerated and read/grepped: `implementation/util.py:30` `fmt_dt` (hand-formats exactly 3 digits); `db.py:139` `now_str`, `db.py:164` `new_row` (`created_at`), `db.py:190` `touch` (`updated_at`); `response.py:23` `jsonable` (datetime → `fmt_dt`), `response.py:43` `api_request_timestamp`; every `fmt_dt`/`now_str` callsite — `customers.py:110` `attestation_at`, `customers.py:164` identity-check `expires_at`, `orders.py:253,354` `submitted_at`/`dispatched_at`, `compliance.py:142` `recorded_at`, `compliance.py:313` `decided_at`, `partners.py:120` `evaluated_at`, `partners.py:215-216,281-282` certification `issued_at`/`expires_at` (issue + renew), `attempts.py:414` `retention_until`, `services/parties.py:333` `blocked_until`; and the opposing set — every `v.req_dt` callsite that stores the raw client string: `attempts.py:97/148` `started_at`, `attempts.py:399/413` `captured_at`, `compliance.py:87/93` `scheduled_at`, `compliance.py:260/267` `response_due_at`, `compliance.py:379/399` and `466/472` `due_at`, `orders.py:86/93` `scheduled_delivery_at`, `reference.py:47-53` `current_utc` (echoed raw, not re-spelled); plus the copy path `attempts.py:313` `order["delivered_at"] = attempt["started_at"]`.
- (c) Adjustment: an initial draft of "every timestamp the API returns carries three fractional digits" would have been a false universal — client-supplied instants and `delivered_at` (a verbatim copy of the client's `started_at`) carry whatever spelling the caller sent. Wording was re-scoped to instants *the server mints or derives*, with an explicit carve-out for body-supplied instants "and any field that copies such a stored value", which keeps `delivered_at`, `current_utc`, `response_due_at`, `due_at`, `scheduled_at`, `scheduled_delivery_at` and `captured_at` correctly described. (PRD §3.10 line 255 independently already pins `delivered_at` = attempt's `started_at`, so no contradiction.)

**Edit 2 — §3.9 case-listing filters**
- (a) Subject: the accepted query-filter set of `GET /violation-cases` and the field each filter matches.
- (b) Enumerated and read: `routes/compliance.py:212-240` `list_cases()` (the only case-listing endpoint — grepped every `db.cases` reader: `compliance.py:226,429,439,461,483`, `services/parties.py:58,125,215,363`, none of the others being a listing); `validate.py:181-195` `enum_filter`/`str_filter`; `compliance.py:44` `SEVERITIES = ("MINOR","MAJOR","CRITICAL")`; the two distinct severity fields on a case (`severity` set at open, `assessed_severity` written at decision — `compliance.py:167-203`, `300-336`), and the `severity` consumers in `services/parties.py:58` (open-case counters, which also key on `severity`) to confirm which field the filter reads.
- (c) Adjustment: the bare word "severity" was ambiguous between `severity` and `assessed_severity` (the impl filters `r["severity"]`, whereas scoring in §3.6/§3.11 keys on `assessed_severity`), so the clause "matching the asserted `severity` carried on the case rather than its `assessed_severity`" was added to prevent a fresh implementer wiring the filter to the wrong field.

**Edit 3 — §4 endpoint-table row for `GET /violation-cases`**
- (a) Subject: same as Edit 2 (the endpoint-table restatement of the filter set), kept in sync so the two PRD locations do not contradict each other.
- (b) Enumerated: `routes/compliance.py:212-240`; the roles clause in the same row against `auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER)` at `compliance.py:214` and the PartnerManager scope forcing at `compliance.py:222-225` (left untouched — outside this edit's subject, and the existing row wording does not misdescribe it).
- (c) Adjustment: used "asserted severity" rather than "severity" for the same disambiguation as Edit 2; the surrounding table row is otherwise verbatim.

## Step 9: Complete PRD — 2026-09-03T18:02:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/`, all editing the single output file `workspace/PRD_COMPLETED.md` in place with targeted Edit calls (a one-shot Step 9 has a known failure mode of no-oping and leaving PRD_COMPLETED.md byte-identical to its source; partitioning also keeps each agent's context inside budget for a 19-module implementation).

Partition: **Pass A** = app.py, start.sh, db.py, errors.py, util.py, response.py, middleware.py, validate.py, routes/reference.py, routes/customers.py · **Pass B** = services/calc.py, services/battery.py, services/sweep.py, routes/orders.py · **Pass C** = services/parties.py, routes/partners.py, routes/attempts.py, routes/compliance.py. Pass A did the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; B and C were told the file already existed and must not be recreated.

### Pass A summary (16 ambiguity-pins, 7 mismatch-revisions)
- §2.1 — insert — ambiguity — whitespace-only header counts as empty for `ERR_MISSING_AUTH_HEADER`; role strings compared exactly/case-sensitively — `middleware.py:41`
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not host wall clock — `response.py:43`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and out-of-enumeration filter values are `ERR_VALIDATION` — `response.py:99`, `validate.py:186`
- §2.3 — insert — ambiguity — every ordering falls back to insertion order as final tiebreak — `db.py:145`
- §2.4 — insert — ambiguity — a row written several times inside one request advances `version` by exactly 1 (`touch()` dedupes per request via `g._touched_rows`) — `db.py:179-190`
- §2.5 — insert — ambiguity — setting the clock to the instant it already reads is not a rewind and still runs the sweep — `reference.py:48`
- §2.5 — insert — ambiguity — `current_utc` echoed exactly as spelled by the caller — `reference.py:51-53`
- §2.6 — insert — ambiguity — required body FK absent or not a non-empty string is `ERR_VALIDATION`/400 at its declared position — `reference.py:116`, `customers.py:47`
- §2.7 tier 6 — insert — mismatch — customer registration is the one place shape precedes body-FK resolution — `customers.py:44-49`
- §2.8 — revise — mismatch — `expected_customer_version` is optional, guard applies only when supplied — `customers.py:123,138`
- §2.9 — insert — ambiguity — decimals render as bare JSON numbers, not quoted strings — `response.py:18-19`
- §3.1 — revise/insert — ambiguity — jurisdiction listing accepts exact-match `code`; `unit_scale_factor`/`max_units_per_order`/`max_units_per_window` rounded half up to 2 dp on store rather than refused; policy `restriction_type` filter accepts the five restricted classes only — `reference.py:97,163-166,192`
- §3.1 — revise — ambiguity — product `restricted_units_per_item` rounded half up to 2 dp on store; `NONE` product with nonzero figure is `ERR_VALIDATION` raised before the `sku` uniqueness check; listing accepts `sku`, and `NONE` is a valid filter value — `reference.py:214-218,239-240`
- §3.2 — revise — ambiguity — `source_signals` must hold ≥1 element; identity-check listings accept a `result` filter — `validate.py:165-166`, `customers.py:177`
- §4 intro — insert — ambiguity — unrouted path → 404 `ERR_VALIDATION`; undefined method → 405; unparseable/non-object body → 400 — `app.py:41-47`, `validate.py:21-23`
- §4 — revise ×4 — mismatch — `GET /jurisdictions`, `GET /jurisdictions/{id}`, `GET /restriction-policies/{id}`, `GET /jurisdictions/{id}/restriction-policies` are readable by all six roles — `reference.py:87-88,94-97,182-183,189-190`
- §4 — revise — ambiguity/mismatch — `GET /customers` also filterable by `latest_identity_check_result` and exact `email`; identity-check version field "Requires" → "Accepts … and checks it when supplied" — `customers.py:81-82,123,177`
- Left unedited: all 60 error rows match §5 identifier-for-identifier; enumerations and numeric bounds; local-time geometry and half-open window incl. wrap branch; identity confidence weights/rounding/bands/`verified_dob`; attestation rules; pagination/envelope/`has_more`; policy ordering; tier-3-before-tier-5 on `GET /customers/{id}`.

### Pass B summary (11 ambiguity-pins, 3 mismatch-revisions)
- §3.3 — insert — ambiguity — orders listing narrowed to the caller's own / carried orders; foreign `customer_id`/`delivery_partner_id` filter is `ERR_FORBIDDEN_RESOURCE_SCOPE` — `routes/orders.py:134-141`
- §3.3 — insert — ambiguity — same narrowing plus `order_id`-filter scope check on the order-line listing — `routes/orders.py:208-221`
- §4 — revise — mismatch — `GET /order-lines/{id}` and `GET /order-lines` also authorise `PartnerManager`; `line_state` filter noted — `routes/orders.py:192,203`
- §3.3 — revise — mismatch — the battery's narrative ordinals contradicted the tier ladder; policy resolution and permissibility (tiers 11/12) run ahead of purchaser eligibility (tier 15) — `services/battery.py:123-144`
- §3.3 — insert — ambiguity — permissibility trio is a per-class outer loop over ascending `restriction_types` (a dry test on an earlier class beats a `PROHIBITED` policy on a later one) — `services/calc.py:213-222`
- §3.3 — insert — ambiguity — a line whose recomputed `line_restricted_units` already equals the stored value is not rewritten (no `version` bump); `NONE` lines never visited — `routes/orders.py:265-269`, `services/calc.py:122-130`
- §3.3 — revise — ambiguity — `provisional_restricted_units` is the sum of per-class totals rounded to two places *again* (a third rounding step for multi-class orders) — `services/calc.py:132-135`
- §3.3 — insert — ambiguity — the two quantity ceilings are also a per-class outer loop — `services/battery.py:154-161`
- §3.3 — insert — ambiguity — compliance-evaluation read model: `restriction_types` re-derived from current lines; policy/exposure anchored on `scheduled_delivery_at` while the clock feeds only block-expiry and scheduled-in-past; full `per_type_exposure` element shape; arrays stop at the first unresolvable class; top-level `window_units_consumed` is the rounded sum; `identity_result` `NONE`, null `purchaser_age_years`/`min_age_required`, `would_route_to` null exactly when a blocking error exists — `routes/orders.py:279-310`, `services/battery.py:49-110`
- §3.4 — insert — ambiguity — a `BLOCK` clearance leaves any existing `hold_reason` in place — `routes/orders.py:331-336`
- §3.6 — revise — ambiguity — the policy set governing handover's `PHOTO_ID` requirement is the set effective at `started_at`, falling back to `applied_policy_ids` for any class that no longer resolves — `services/calc.py:91-102`
- §3.7 — insert — ambiguity — `restock_confirmed` shape failure is `ERR_VALIDATION` before the state guard, but the `false` objection is raised after it — `routes/orders.py:365-369`
- §3.7 — insert — ambiguity — settlement leaves the order's `restriction_types` as submission wrote it — `routes/orders.py:375-380`
- §2.7 — revise — mismatch — tier 19 claimed order-line `quantity ≥ 1` and the at-least-one-line rule as 409 structural constraints with no code named; repinned as tier-10 `ERR_ORDER_HAS_NO_LINES` and tier-7 `ERR_VALIDATION` — `routes/orders.py:170,244`
- Left unedited: double rounding per line then per class; line visit order; `compute_restriction_types`; closed-closed policy resolution and positional `applied_policy_ids`; rolling-window look-back; identity confidence; `window_error`; submit freeze/route/side-effects and the `AUTO_CLEARED` shortcut; create-order defaults; clearance/dispatch gates; all three sweep steps.

### Pass C summary (25 ambiguity-pins, 7 mismatch-revisions)
- §2.4 — revise — mismatch — derived-field recomputation counts as a mutation *only when it actually changes a stored value*; the refusal/`open_case_count` example kept (literally true) with the no-change cases added — `db.py:172-190`, `services/parties.py:102,133,152,249,262,270,329-338`
- §2.11 — insert — ambiguity — `compliant_handover_count` added to the re-counted-from-source list — `services/parties.py:255-264`
- §2.8 / §4 / §3.9 — revise ×3 — mismatch — `expected_violation_case_version` is optional, checked only when supplied; `due_at` (tier 8) objection precedes the case-state guard (tier 10) — `routes/compliance.py:377-389`
- §3.4 — insert — ambiguity — the posture hold rewrites only `PREVERIFIED`/`COMPLIANCE_CLEARED`; an `AUTO_CLEARED` order is held with its compliance state untouched — `services/parties.py:172-173`
- §3.5 / §4 — insert — ambiguity — `dispatch_eligible` courier filter; `PartnerManager` listing narrowing with `ERR_FORBIDDEN_RESOURCE_SCOPE` on a foreign filter; `Courier` not narrowed on a single courier read — `routes/partners.py:162-186`
- §3.5 — insert — ambiguity — training freshness anchored at the date's UTC midnight (exactly 90 days still fresh); neither issuance nor renewal recomputes `compliance_score`, so a courier below 70.00 can hold an `ACTIVE` cert until the next recomputation re-suspends it — `routes/partners.py:222,275,287-288`
- §3.5 — insert — ambiguity — revocation-driven abort writes the same `CERTIFICATION_SUSPENDED`/`COURIER_CERTIFICATION_SUSPENDED` literals, unconditionally — `routes/partners.py:305`, `services/parties.py:289,296`
- §3.6 — revise — mismatch — "certification validity" dropped from `started_at`'s evaluation-instant list — `routes/attempts.py:120,236-238`
- §3.6 — insert — ambiguity — attempt read/list scoping: `Courier` filter forced with hard rejection; `PartnerManager` hard-scoped on a single read but silently narrowed on the listing; capture listing scoped like the single read — `routes/attempts.py:171-198,424-429`
- §3.6 — revise — mismatch — the tier-13(d) certification gate reads each row's **stored** `state`, not its state as at `started_at` — `routes/attempts.py:234-240`
- §3.6 — revise — ambiguity — `recipient_age_years` uses the **UTC** date of `started_at`, not the jurisdiction-local date the expiry test uses — `routes/attempts.py:256`
- §3.6 — insert — ambiguity — the id-check is admissible on an order with no restricted class (empty policy set ⇒ threshold 0 ⇒ always `ID_VERIFIED`), and such a handover *does* earn credit — `routes/attempts.py:231,257,265,328-332`
- §3.6 — insert — ambiguity — capture storage is not gated on attempt state; global `content_hash` uniqueness checked ahead of the per-kind constraint — `routes/attempts.py:389-406`
- §3.6 — revise — ambiguity — "increments by one" → "re-counts … which this handover raises by one" — `services/parties.py:255-264`
- §3.6 — insert — ambiguity (**pass B handoff note 1**) — handover is not a tier-11 checkpoint and never raises `ERR_NO_EFFECTIVE_POLICY`; the final exposure covers only classes resolvable at `started_at`, stopping at the first unresolvable one, with no `applied_policy_ids` fallback (unlike the capture test) — `routes/attempts.py:316-317`, `services/calc.py:62-73,105-133`
- §3.7 — insert — ambiguity — the state objection precedes `ERR_REFUSAL_REASON_NOT_ALLOWED`; auto-refusal case `summary` literal pinned — `routes/attempts.py:349-352,371`
- §3.7 — revise — mismatch — `blocked_until` uses an at-or-above test on 3 strikes, so the fourth and every later compliance refusal re-stamps it forward — `services/parties.py:331-336`
- §3.7 — insert — ambiguity — an order returned by the **abort** route has no `REFUSED` attempt and hence no governing reason; that is not `COURIER_FAULT` — restocking tier applies, no delivery fee refunded — `services/parties.py:378-398`
- §3.8 / §4 — insert — ambiguity — undocumented `scenario_type` filter on secret-shopper tests — `routes/compliance.py:116`
- §3.8 — insert — ambiguity — no state guard on record-outcome (re-recordable, re-derives the verdict, opens a further case on a fresh `FAIL`, omitted `findings` writes null); auto-shopper case carries null `delivery_attempt_id` plus its `summary` literal — `routes/compliance.py:131-161`
- §3.8 — insert — ambiguity — a recomputation landing on the score already stored writes nothing — `services/parties.py:270-272`
- §3.9 — insert — ambiguity — `PartnerManager` case-listing narrowing plus foreign-filter rejection — `routes/compliance.py:222-225`
- §3.9 — insert — ambiguity — optional `notes` written only when supplied (never clears); only reopen always writes — `routes/compliance.py:268-269,314-315,451-452,494-495`
- §3.9 — insert — ambiguity — a `SUBSTANTIATED` decision missing `assessed_severity` is a tier-7 `ERR_VALIDATION` ahead of the state guard; on `DISMISSED` a supplied value is discarded — `routes/compliance.py:308-324`
- §3.9 — insert — ambiguity — `risk_contribution` is severity points only (no tier multiplier, no halving), stamped at substantiation and never refreshed as the case ages — `services/parties.py:109-119`, `routes/compliance.py:320`

**Resolution of pass B's handoff note 2 (§2.4 version bumps).** `db.touch()` bumps `version`/`updated_at`, but every recompute in `services/parties.py` calls it behind an equality guard (`recompute_partner_scores:102`, `recount_partner_cases:133`, `rederive_posture:152-153` — which returns early and so also skips the courier-gate and order-hold cascades, `rederive_courier_gates:249`, `recount_compliant_handovers:262`, `recompute_courier_score:270`, `rederive_latest_identity_result:311`, `recompute_refusal_strikes:329-338`). §2.4's general claim was therefore made conditional ("only when the recomputation actually changes a value stored there") while keeping the example sentence, which *is* literally true — a compliance refusal always opens a new `OPEN` case, so `open_case_count` always changes. Concrete counter-examples were added (a `PASS` shopper outcome re-deriving an unchanged `compliance_score`; a posture derivation landing on the posture already held). The one unconditional recompute outside pass C's partition (`routes/reference.py:173-176`, `active_policy_count`) always genuinely changes, so the wording stays safe.

**One discrepancy pass C found but deliberately did not pin:** `services/parties.py:384-385` (`governing_refusal_reason`) sorts ascending and takes the last row, so a tie on `started_at` would resolve to the *later* `created_at`, whereas §3.7 says ties break to the earlier `created_at`. Unreachable — an order can hold at most one terminal attempt, since a second attempt requires `fulfillment_state` `DISPATCHED` and nothing restores that from `OUT_FOR_DELIVERY`/`RETURN_IN_TRANSIT`/`DELIVERED` — so the prose was left alone rather than pin a distinction no request can exhibit.

### Orchestrator verification of Step 9 output
- `PRD.md` 446 lines / 103,123 B → `PRD_FINALIZED.md` 446 lines / 103,788 B → `PRD_COMPLETED.md` 446 lines / 122,703 B.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → **differs** (the known no-op failure mode did not occur); 65 lines changed versus PRD_FINALIZED.md, +18,915 B of pinning prose, all in-paragraph.
- Integrity: 5 top-level sections present, `## 5. Error Code Catalogue` intact with all 60 `ERR_` rows, last line `| `ERR_WINDOW_UNIT_LIMIT_EXCEEDED` | 422 |` — a real section boundary, no truncation.
- No file under `implementation/`, `test_suite/` or `test_helpers/` has an mtime newer than the green sweep's `results.1.json` (epoch 1788456073), confirming Steps 8 and 9 touched documentation only and the 8×132/132 result still describes the code on disk.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
