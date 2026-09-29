# Worklog — task_2575_home_oxygen_respiratory_therapy_service

## Step 1: Create task directory — 2026-09-03T15:11:20.326Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2575_home_oxygen_respiratory_therapy_service` and its `workspace/` subdirectory. Index 2575 was pre-assigned by the invoking pipeline (no `./tasks/` scan performed, per instruction — 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate scaffold artifacts — 2026-09-03T17:35:00Z

Wrote the three scaffold files from the scenario description plus
`skills/prd-bench-scaffold-generator/SKILL.md` only (no sibling task inspected).

- `SCAFFOLD.yaml` (§1.0–§1.7, 3779 lines): 11 entities, 10 state machines, 2 OCC
  concurrency rules, 11 calculations, 80 ordered validations, 69 endpoints,
  73 errors, 7 roles. Contains neither design key.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 1803 lines): 9 rule_ids x 2 instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 5815 lines): 9 sections, 88 instances
  (67 full + 21 `excluded_because` stubs).

`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py <task dir>` reports
`VERDICT: clean lint` over 1267 scanned calls.

### Step 2 — verbatim subagent summary (2026-09-03T17:36:10Z)

All three scaffold artifacts are complete, PyYAML-valid, and pass the generator's own linter.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2575_home_oxygen_respiratory_therapy_service/SCAFFOLD.yaml` — 3779 lines, §1.0–§1.7, contains neither design key
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1803 lines, single key `scaffold_difficulty_design`
- `.../SCAFFOLD_CORNER_DESIGN.yaml` — 5815 lines, single key `scaffold_corner_design`
- `.../worklog.md` — Step 2 entry appended

`scaffold_lint.py` -> `VERDICT: clean lint` (69 endpoints, 11 entities, 18 §1.8 instances, 67 §1.9 non-stub instances, 1267 calls scanned).

## SCAFFOLD.yaml counts

11 entities, 10 state machines (Patient, RentalContract x2 parallel dimensions, Placement, EquipmentUnit, RouteStop, DeliveryRoute, CMN, RecallNotice, TravelAuthorization), 2 OCC concurrency rules, 11 calculations, 80 ordered validations, 69 endpoints, 73 errors, 7 roles. Profile: compliance_audit / temporal_windowing, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, graph topology, parallel shape, segregation_of_duties, immediate consistency. All 73 error ids are referenced by at least one design instance.

## §1.8 — 9 rule_ids x 2 = 18 instances

`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 — 9 sections, 88 instances (67 full + 21 `excluded_because` stubs)

entities 15 (15/0), state_machines 20 (15/5), calculations 18 (12/6), validations 19 (13/6), endpoints 6 (4/2), errors 1, rbac 3, cross_cutting_complexity_layers 5 (3/2), consistency_model 1. Every stub's `difficulty_instance` names a real §1.8 instance; all 106 names are unique across the union.

## Design adjudications

- ERR_QUALIFYING_TEST_STALE placed at priority 49, above the documentation threshold at 50 — otherwise a stale study always surfaces as ERR_DOCUMENTATION_INCOMPLETE (c_currency 0 caps the score at 80) and the error is unreachable.
- Priority 35 (ERR_CONTRACT_BILLING_SUSPENDED) masks priority 95 (cap exhaustion) on any CAP_REACHED contract, so the cap corner reaches 95 via the transfer-request/cancel pair, which the scaffold notes always resumes on the ACCRUING branch.
- `PLACED -> RECALLED_OUT_OF_SERVICE` is terminal, so servicing the quarantined unit does not unblock resume-billing — asserted twice in the same recipe.
- Travel supply STEP 7 reads `cylinders_raw`, never the surcharged total; the new `rate_threshold_triggers` instance pins 5 raw (surcharge 0, total 5) vs 6 raw (surcharge 1, total 7) and shows a 25-hour trip with 594 more litres still landing on 6 raw / total 7.
- `PATCH /cmns/{id}` exists only on the RETURNED_FOR_CORRECTION -> DRAFT edge. Consequence made explicit: a correction that drops the score below 85.00 strands the certificate in DRAFT (submit 422, PATCH 409); the only exit is DRAFT -> VOIDED. The endpoints instance asserts that ERR_INVALID_STATE.
- TravelAuthorization creation is deliberately not gated on `service_status == IN_SERVICE` (only patient ACTIVE, CMN ACTIVE, contract not CLOSED, no compliance hold), so travel can be authorised while a contract is still PENDING_SETUP.
- Because the role check sits at priority 3 above all existence checks, both RBAC instances probe the whole matrix against a non-existent id and assert 403-vs-404 for identical path and body — that contrast is what proves the refusal came from the matrix.
- `planned_stop_count` is a live count of PLANNED stops, so the manifest of a fully completed route reads `planned 0 / completed 1`; asserted in the computed-read instance.
- Fixes applied this session: quoted `"$.data[0].field"` captures (bare `[` breaks YAML flow mappings), rewrote the PATCH instance after finding PATCH is state-gated, and corrected `approved_by_user_id` -> `decided_by_user_id` in the §1.8 travel-hold assert.

## Step 3: Copy shared files — 2026-09-03T17:34:44.662Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:53:20Z

Orchestrator truncation check (per the known doc-generator failure mode): `wc -l` = 608;
`tail -12` ends on the last complete row of the §5 two-column error table
(`| \`ERR_NO_PLACED_EQUIPMENT\` | 422 |`); `grep '^## '` shows all five top-level
sections present and §5 is the final one. Ends at a real section boundary — NOT
truncated, so no regeneration was needed.

Verbatim subagent summary follows.

---

PRD generation is complete and verified.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2575_home_oxygen_respiratory_therapy_service/workspace/PRD.md`

- **608 lines / 18,934 words**
- **Exact final heading:** `## 5. Error Code Catalogue` (file ends on the last complete 2-column table row, `| \`ERR_NO_PLACED_EQUIPMENT\` | 422 |`, at a real section boundary — no truncation, no audit footer)
- Built incrementally: one `Write` for chunk 1, then heredoc `cat >>` appends for every subsequent chunk.

## Section list
1. Introduction
2. Global Specifications & System-Wide Principles — 2.1 Role-Based Access Control - 2.2 API Response Structure (verbatim block) - 2.3 Pagination - 2.4 Resource Identity, Timestamps and Revision Counters - 2.5 Nested Path Resolution - 2.6 The Logical Clock - 2.7 Stale-Read Protection on Certificate and Travel Creation - 2.8 Precision, Rounding Order and Unit Arithmetic - 2.9 Parallel State Dimensions and Cascade Propagation - 2.10 The Order in Which a Request Is Judged - 2.11 Safety Posture and the Compliance Hold
3. Business Logic & Workflows — 3.1 Branch Network and Fleet Onboarding - 3.2 Intake and Qualifying Studies - 3.3 The Certificate of Medical Necessity - 3.4 Opening a Capped-Rental Contract and Selecting Equipment - 3.5 Route Planning, Stop Scheduling and Field Execution - 3.6 In-Home Setup, Education and the Safety Assessment - 3.7 Malfunction Response, Preventive Maintenance and Recall Remediation - 3.8 Capped-Rental Billing, the Cap Ceiling and Reversal - 3.9 Travel Supply Authorization, Branch Transfer and Discharge (9 subsections, within the 5-9 rule)
4. Endpoint Definitions (4-column table, 69 rows)
5. Error Code Catalogue (2-column table, 73 rows)

## Coverage
11/11 entities - **137/137** entity field names - **82/82** endpoint body/query/path identifiers - 69/69 endpoints - 80/80 validations - 11/11 calculations - 73/73 errors - 57/57 transitions across 10 state machines - 2/2 concurrency rules - 7/7 roles.

## Hard Contract results
- **Contract 1 — Field-Name Coverage: PASS.** Mechanical diff (YAML-extracted required set vs. inline-backtick tokens with fenced blocks stripped): 137 entity fields + 82 endpoint identifiers, 0 missing. Re-verified excluding backticked path spans as evidence — still 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 57 transitions (both endpoint states present and each described in prose), all 80 validations rendered as the §2.10 ladder (exactly 80 numbered items) with `applies_to` scopes stated, both OCC rules in §2.7, all 11 calculations with pinned rounding orders and worked numbers, both dual-variant calculations (`oxygen_safety_risk_score`, `cap_month_position`) rendered with both variants and a divergence example, both depth-4 cascades rendered hop-by-hop, sibling branches (setup PASS vs. FAIL, transfer complete vs. cancel, post vs. reverse) rendered at equal density, all enum constraint values present, all 73 error ids mentioned in §2/§3 prose before the §5 table.
- **Contract 3 — §3 Path Purity: PASS.** 0 backticked tokens in §3 that start with `/`, are a bare HTTP method, or combine method+path. Also verified: no `:=`, `->`, `==`, `>=`, `&&` pseudocode operators anywhere, and no fuzzy words (`approximately`/`roughly`/`conservatively`).
- §2.2 confirmed byte-identical to `section-2.2-response-structure.md`; §4 = exactly 4 columns, §5 = exactly 2 columns.

## Doc adjudications
1. **§2.10 renumbered 1-80.** Scaffold priorities are gapped (1-42, 49-51, 53-56, 60-67, 70-81, 85-92, 95-97); the ladder preserves relative order exactly but uses dense 1-80 numbering, and no priority numbers appear anywhere in the prose.
2. **§3 consolidated to 9 subsections** (an initial 11-subsection layout would have broken the 5-9 rule).
3. **`ERR_SEGREGATION_OF_DUTIES` sits at ladder position 4, ahead of path existence.** Documented faithfully, with the added explanation that when the certificate cannot be located there is no stored submitter/signer to compare against, so the check cannot fire and `ERR_CMN_NOT_FOUND` surfaces instead.
4. **`ERR_WINDOW_OUTSIDE_SHIFT` conflict resolved in favour of the validation check.** The error catalogue's condition text describes the window extended by `service_minutes`, while the validation check extends it by the branch's `tank_exchange_buffer_minutes`. The PRD documents the buffered span (turnaround buffer), matching the validation and matching `ERR_ROUTE_STOP_WINDOW_CONFLICT`, which uses the same buffered half-open interval.
5. **`removal_reason` value `TRANSFER`.** The Placement machine declares `PLACED -> REMOVED` with reason `TRANSFER` for a transfer opened with a null receiving branch, but the patient transfer request requires `receiving_branch_id`. Documented conditionally, with the explicit note that a normal branch-to-branch transfer leaves placements untouched and only moves the billing dimension.
6. **Recall notice inputs.** Only `model_code` and `severity` are client-supplied; `issued_at` is stamped from the logical clock. Documented accordingly, with the frozen-snapshot vs. live-recount distinction between `affected_unit_count`/`auto_quarantined_unit_count` and `remediated_unit_count` made explicit.
7. **Derived consequence stated explicitly:** because the service-month basis ignores `posted_months`, a `COMPETITIVE_BID_SINGLE_PAYMENT` contract at its cap can never reverse back to `ACCRUING`. This is an inference from the pinned formula, spelled out so the implementer does not have to derive it.
8. **§4 descriptions rewritten** to strip scaffold-internal references (`calculations.*`, `concurrency_rules[...]`, `A -> B` arrows, `§1.x` cross-references) into natural language pointing at PRD sections.
9. **Two late coverage patches:** `documentation_score` added by name to §3.3, and a sentence naming all twelve path parameters added to §2.5 — both required to close Contract 1 without relying on backticked paths as evidence.
10. **§2.9 forward references corrected** from §3.7/§3.8 to §3.6/§3.7 after the §3 consolidation.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-03T18:52:00Z

Launched concurrently with Step 6 in a single assistant message, so the impl generator
was physically unable to read `test_suite/` (it did not exist at its spawn time).
Orchestrator placement check: `test_helpers/` and `test_suite/` are at the TASK ROOT and
`workspace/` contains only INSTRUCTION.md, PRD.md, implementation/ — no misplaced test
dirs to relocate. `PYTHONPATH=. pytest --collect-only -q test_suite/` -> 157 collected, 0 errors.

Verbatim subagent summary follows.

---

The unit-test suite for task 2575 is complete and audited.

## Files written

All at the task root `/home/ubuntu/github/CodingPRD/tasks/task_2575_home_oxygen_respiratory_therapy_service/` — nothing under `workspace/`, and `workspace/implementation/` was never read or written by me or any subagent.

**`test_helpers/` — 2,929 lines**

| file | lines |
|---|---|
| `__init__.py` | 48 |
| `api_client.py` | 374 |
| `api_errors.py` | 189 |
| `assertions.py` | 447 |
| `constants.py` | 143 |
| `factories.py` | 261 |
| `fixtures.py` | 871 |
| `test_users.py` | 91 |
| `types.py` | 505 |

**`test_suite/` — 8,502 lines**

| file | lines | tests |
|---|---|---|
| `conftest.py` | 46 | — |
| `test_01_dual_variant_and_combinatorial.py` | 679 | 12 |
| `test_02_lifecycle_cycles_and_cascades.py` | 664 | 19 |
| `test_03_error_precedence_and_boundaries.py` | 551 | 14 |
| `test_04_dependencies_intervals_and_compensation.py` | 760 | 16 |
| `test_05_entity_contracts.py` | 1067 | 15 |
| `test_06_lifecycle_transitions.py` | 956 | 15 |
| `test_07_computed_values.py` | 998 | 12 |
| `test_08_rejection_rules.py` | 1570 | 40 |
| `test_09_endpoints_and_access_control.py` | 793 | 9 |
| `test_10_concurrency_and_consistency.py` | 418 | 5 |

## Coverage

- **Queue A (difficulty index): 18 of 18 instances translated -> 61 tests.** Every instance has >=2 tests; none skipped.
- **Queue B (corner index): 67 of 67 non-stub instances translated -> 96 tests.** Every non-stub instance has >=1 test; none skipped. All **21 stubs** correctly left untranslated (verified by parsing `excluded_because:` + absent `test_recipe:`): 5 `state_machines`, 6 `calculations`, 6 `validations`, 2 `endpoints`, 2 `cross_cutting_complexity_layers`.
- **Total: 157 test functions.**

## Audits run

- `ast.parse` clean on all 20 files; `PYTHONPATH=. python3 -m pytest --collect-only -q test_suite/` -> **157 collected, 0 errors**; `import test_helpers` OK.
- **Design tags:** 157 tags for 157 tests — exactly one per test, always the last docstring line, every tag resolving to a real `name:` in the source yaml, **0 stub tags, 0 dangling tags, 0 dual/untagged tests**.
- **PRD citations:** all 157 `PRD: "..."` quotes are **byte-exact substrings** of `workspace/PRD.md` (strict, not whitespace-normalized).
- Zero occurrences of `scaffold` / `SCAFFOLD_` / `Table N` / `§1.x` in generated prose; zero `skip`/`xfail`/`print`/`time.sleep`.

## Instances SKIPPED — none

All 85 in-scope instances passed the PRD-first two-condition filter at the instance level.

## Assertion legs dropped (per-leg PRD-derivability, condition C2)

1. `Corner/entities/replaces_unit_id_self_reference...` — RETIRED-predecessor-at-a-different-branch -> `ERR_REPLACED_UNIT_NOT_REPLACEABLE`. PRD imposes only the "`IN_QUARANTINE` or `RETIRED`" condition with **no same-branch requirement**, so a PRD-only implementer accepts that call.
2. `Corner/entities/qualifying_test_is_immutable...` — "no mutation surface at all" leg: PRD pins no status/error id for an undeclared method.
3. `Corner/entities/body_foreign_key_references_not_found_rejected` — literal "patient version is still `${p_ver}`"; the recipe's own certificate chain bumps it first (recipe-internal inconsistency). Replaced with the equivalent ladder-ordering assertion.
4. `Difficulty/combinatorial_formula/monthly_allowable_per_line_rounding_order...` — per-line intermediates 6875/1627: the API exposes no line-item field, so unobservable; the pinned total 8502 (and `!= 8503`) is asserted instead.
5. `Difficulty/boundary_precision_check/documentation_score_exactly_85...` — patient-mirror leg depending on "most-recently-created certificate" when two certificates share one logical instant.
6. `Corner/calculations` — four legs on unemitted intermediates (`documentation_score` components, `usable_hours`, a self-admittedly non-discriminating alternative sum, and a statement about the recipe rather than an outcome).
7. `Corner/validations/cap_reversal_and_exhaustion...` — `service_month_basis_position == 2`; the PRD's candidate-month rule yields **1**.
8. `Corner/endpoints/patch_endpoints_recompute...` — `p_ver_end == p_ver_mid + 1`; the PRD derives **+2** (re-submission mirrors onto the patient). Kept exact by re-reading immediately before the PATCH.
9. Cap-summary `variant_applied` enum literal in one difficulty test (PRD prose never pins that string).
10. Timestamp-format accommodation across several files: the design writes computed instants bare (`...T14:00:00Z`) while the PRD mandates three fractional digits, so those are asserted by prefix + `is_iso8601_timestamp` rather than exact equality.

## Two PRD defects worth flagging upstream

- **`ERR_CYLINDERS_NOT_APPLICABLE` is self-contradictory.** §3.5 says the error fires when a non-zero cylinder count is supplied on a `PICKUP`/`PORTABLE_REFILL` stop; the §2.10 ladder entry says it fires when the count **is zero or omitted** on those stop types. The two readings invert each other, so that leg was dropped. Note that the shared fixture `schedule_pickup_stop` sends `cylinders_requested: 0`, which assumes the §3.5 reading is intended — if the ladder wording is authoritative instead, several pickup-path setups would need changing.
- **`consistency_model/malfunction_cascade...` contradicts the PRD.** The design expects a billing post to succeed at zero cents after a TIER_1 cascade, but the PRD twice requires `monthly_allowable_cents > 0` or `ERR_NO_PLACED_EQUIPMENT`. The test asserts the PRD direction (`test_month_posting_immediately_after_a_tier_one_report_sees_the_empty_placed_set` in `test_10`) — that is the single test to revisit if the design's literal expectation is authoritative.

## Step 6: Generate implementation — 2026-09-03T18:52:00Z

Launched concurrently with Step 5 in the same assistant message.

Verbatim subagent summary follows.

---

Implementation complete and verified. Cleanup done: both smoke servers (pids 105241, 120460) and the final verification server (pid 154301) were killed by exact pid only — no pattern kills at any point.

## Files written

Root: `/home/ubuntu/github/CodingPRD/tasks/task_2575_home_oxygen_respiratory_therapy_service/workspace/implementation/`

Shared layer (6 modules, 1595 lines):
- `core.py` (520) — Flask app factory bits, `Store` (11 in-memory dicts + logical clock + `_seq`), envelope/`respond`/`paginate`, RBAC role constants + `authenticate`, `ERROR_STATUS` (73 ids -> HTTP), `ApiError`, datetime/date/month parsers, `touch`/`base_row`/`order_key`, `CLOCK_START = 2026-08-01T00:00:00Z`
- `calc.py` (474) — all 11 calculations, `Decimal` + ROUND_HALF_UP throughout
- `domain.py` (273) — row lookups, CMN mirror re-derivation, risk re-scoring, allowable recompute, route roll-ups/bubble-up, contract-suspension cascade, `clock_sweep`
- `serial.py` (250) — one serializer per entity; `remediated_unit_count` is a live recount
- `validate.py` (170) — `Field`/`validate` schema layer (type, enum, range, length, nullability, defaults)
- `app.py` (78) — registers 12 blueprints under `/home-oxygen`
- `requirements.txt` (1), `start.sh` (10) — guarded `pip install`, `threaded=False`, `use_reloader=False`, `PORT` env

Route layer (13 modules, 2536 lines): `branches.py` (97), `patients.py` (281), `qualifying_tests.py` (105), `cmns.py` (303), `contracts.py` (442), `equipment_units.py` (151), `placements.py` (115), `delivery_routes.py` (185), `route_stops.py` (382), `recall_notices.py` (159), `travel_authorizations.py` (93), `clock.py` (43), `__init__.py` (0).

Total 4132 lines. All 19 `.py` files pass `ast.parse` (no truncation).

## Coverage

- **Endpoints: 69/69** — `app.url_map` yields exactly 69 non-static rules, matching the scaffold's 69.
- **Errors: 73/73** — programmatic cross-check of the scaffold error catalog against `core.ERROR_STATUS`: 0 missing, 0 HTTP-status mismatches, 0 extras, and 0 catalog ids never raised anywhere in the code.
- **Validations: 80/80** priority entries realized as ordered `raise ApiError(...)` sequences per endpoint (global precedence ladder: auth -> SoD -> path existence -> schema -> pagination -> body FK -> OCC -> uniqueness -> state -> business safety -> referential -> temporal -> capacity -> fiscal).
- **Calculations: 11/11** in `calc.py` (monthly allowable/cap, travel supply chain, risk factors + two scoring variants, stop litres, recall deadline, equipment selection, remediated recount).

## Smoke test

Fresh boot on port 18613 via `bash start.sh` (listener pid 154301): server came up in under 6s, logical clock read exactly `2026-08-01T00:00:00.000Z` on first request, store was empty (`total_count: 0` on `GET /patients` — no seeded data), envelope shape correct (`meta.api_request_id` / `api_request_timestamp` / `response_type` / `data`, pagination meta on list reads). Verified 201 branch create (version 1), 400 `ERR_INVALID_REQUEST` on a missing required field, 401 `ERR_UNAUTHENTICATED`, 404 `ERR_PATIENT_NOT_FOUND`, and a clock advance returning the sweep counters. No persistence artifacts written to disk.

Earlier in the run, three scripted end-to-end scenarios passed against a live server: happy path (allowable 6875, first month 6875 over 31 days, route bubble-up with 1360 litres, CLASS_I recall cascade with deadline 2026-08-06); setup-failure four-hop cascade (`safety_findings_count 3`, risk factors 100/100/60/0/0 -> `initial_assessment_score 54.0`, contract SUSPENDED/SETUP_FAILED, placements REMOVED/SETUP_FAILED, units IN_QUARANTINE/SAFETY, allowable 0); travel supply (12h, factor 1.18, effective 2.36 LPM, base 1699 + reserve 339 = required 2038 -> 3 cylinders), 412 stale-version on both OCC guards, pickup schedule -> cancel revert -> re-schedule -> complete (contract RETURNED, allowable 0, unit IN_STOCK), recall close gating, clock monotonicity.

**One real defect found and fixed**: `clock_sweep` crashed with `'<' not supported between instances of 'str' and 'datetime.date'` because `recert_due_date` is stored as an ISO string. Fixed in `domain.py:258-264` by normalizing to an ISO string and comparing lexicographically; re-verified live (`expired_cmn_count: 2, suspended_contract_count: 1`). I audited every other stored-date comparison (`next_pm_due_date`, `test_validity_expires_at`, `transfer_effective_date`) — no further instances.

## Interpretation decisions where PRD prose was ambiguous

1. **Route roll-up refresh points** — re-derived only on stop create, stop cancel, route lock, and manifest read. `miss` alone decrements `planned_stop_count`; a generic `complete` leaves the route row untouched except for bubble-up.
2. **Version-bump discipline** — exactly one `touch()` per mutated row per request: `_resequence(route, skip_touch=(new_id,))` keeps a freshly created stop at version 1 while renumbering peers, and `if not bubble_up_route(route): touch(route)` in `miss` avoids a double route bump.
3. **Undeclared preconditions -> `ERR_INVALID_STATE` (409)**, placed last in each ladder: PICKUP stop creation on a non-PLANNING route, `complete-setup` when the contract is not PENDING_SETUP, `complete-setup` PASS path with no RESERVED placement, travel approve on a suspended or not-in-service contract, and `close` on an already-CLOSED notice/contract.
4. **Recall counters** — `affected_unit_count` and `auto_quarantined_unit_count` are frozen snapshots taken *before* the cascade mutates anything (`auto_quarantined` is 0 for non-CLASS_I); only `remediated_unit_count` is a live recount, which is what makes the close-gate meaningful.
5. **CMN mirror** — a write against the newest certificate always re-stamps `Patient.current_cmn_status` (and bumps the patient); a write against an older certificate only touches the patient when the mirrored value actually changes.
6. **Window overlap** — half-open buffered intervals using the branch's `tank_exchange_buffer_minutes`: `start < other_end + buffer and other_start < end + buffer`, with the buffer also applied to the shift-containment check.
7. **`denial_reason` on travel deny** — accepted and validated but not persisted, since the TravelAuthorization entity declares no such field.
8. **Unknown request-body fields are accepted and ignored** — neither the scaffold nor the PRD requires strict rejection (confirmed by grep).

## Step 7: Run tests and iterate — 2026-09-03T19:12:00Z

Orchestrator independent verification (per the known failure mode where a Step 7 subagent
reports a clean sweep without leaving artifacts): all 8 `workspace/implementation/results.N.json`
files exist (timestamped 19:05) and each reads `passed 157 / total 157 / failed 0 / skipped 0`.
The claim is substantiated — no re-run needed.

Step 8 is NOT skipped: Step 7 applied 2 `test_suite/` fixes, so the skip condition
(0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes)
does not hold.

Verbatim subagent summary follows.

---

All 8 parallel rounds pass 157/157 with zero skips. Exiting.

## Summary

**Iterations run:** 2 (each an 8-round parallel `setsid` sweep, 157 tests per round).

- Iteration 1: all 8 rounds 155/157. The **same 2 tests failed in all 8 rounds** — deterministic, not flaky. No timeout/connection-refused noise, no `Terminated` pattern in the logs.
- Iteration 2 (after fixes): **8/8 rounds green, 157/157, union of failures across rounds = NONE.**

**Tests deleted:** none. Both failures survived STEP 1 — each asserted rule appears verbatim in PRD.md and is uniquely derivable, so neither qualified for deletion. Both were STEP 2 test-vs-PRD inconsistencies.

**Fixes applied to `test_suite/`:**

- `test_suite/test_05_entity_contracts.py:1037` — `test_replacement_unit_must_name_an_out_of_service_predecessor` had a stray hardcoded `assert refused.status_code == 409` that contradicted PRD §5 (`| ERR_REPLACED_UNIT_NOT_REPLACEABLE | 422 |`) *and* contradicted `test_helpers/api_errors.py:161`, which already maps that error to 422. Corrected to 422; the implementation's 422 was PRD-correct.
- `test_suite/test_06_lifecycle_transitions.py:675` — `test_contract_closes_only_from_a_returned_service_dimension_then_locks_billing_out` issued the equipment-assignment probe as `BRANCH_MANAGER`, so the PRD-faithful server correctly returned `ERR_UNAUTHORIZED` (ladder pos. 3) before ever reaching the `ERR_CONTRACT_CLOSED` check the test was written to observe. PRD §4 authorizes that endpoint for **RespiratoryTherapist** only; switched to `RESPIRATORY_THERAPIST` (already imported). This makes the test more faithful — it now actually exercises ladder pos. 34, which PRD lists equipment assignment among.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:** none. Neither failure traced to an implementation defect; in both cases the implementation was already the PRD-faithful side.

**On the two defects the Step 5 generator flagged** — both were non-issues under the protocol:

1. `ERR_CYLINDERS_NOT_APPLICABLE` is **not** self-contradictory. The §2.10 ladder states each entry as *the condition that must hold for the request to pass*, not the firing condition (cf. pos. 60, `ERR_INVALID_WINDOW` — "`window_end_utc` is strictly after `window_start_utc`"). Read that way, pos. 74 and §3.5 agree: the error fires on a **non-zero** count. The `schedule_pickup_stop` fixture sending `cylinders_requested: 0` is correct, and `test_a_pickup_stop_may_not_request_cylinders` passes in all 8 rounds.
2. `test_month_posting_immediately_after_a_tier_one_report_sees_the_empty_placed_set` asserts PRD §3.8 verbatim ("`monthly_allowable_cents` must be greater than 0, or the post is refused with `ERR_NO_PLACED_EQUIPMENT`", also ladder pos. 80). The test is PRD-faithful and already passing; the conflicting "zero-cent post succeeds" expectation lived only in SCAFFOLD, which is not the contract.

One unexercised observation, deliberately left alone (no failing test, and changing it risks regressing a green suite): `calc.py:450 remediated_unit_count` does not exclude `RETIRED` units, though PRD §3.7 says a retired unit "is excluded from every recall count." No test in the suite distinguishes this case.

## Step 8: Finalize PRD — 2026-09-03T19:16:00Z

Not skipped (2 `test_suite/` fixes in Step 7), but the subagent concluded — with a per-item
pre-edit enumeration log — that both fixes were pure test bugs sitting on PRD text that
already uniquely determined the behavior the implementation exhibits. Outcome:
`PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (both md5 `964b3f99466110415730d7919eb753f3`).
Orchestrator decision: accept this. A zero-edit Step 8 is explicitly legitimate when the
Step 7 diff contains 0 implementation fixes and 0 deletions; Step 9's full scan runs regardless
and will adjudicate the residual items Step 8 flagged as out-of-scope.

Orchestrator decision on Step 9 execution: run it as THREE sequential file-partitioned
passes over `implementation/` rather than one pass. A single subagent scanning 19 modules /
4132 lines / 69 endpoints reliably under-scans, and the tell — `PRD_COMPLETED.md` coming out
byte-identical to its source — is indistinguishable from "nothing to fix". Partition:
pass A = shared layer (core/calc/domain/serial/validate/app), pass B = branches, patients,
qualifying_tests, cmns, equipment_units, clock routes, pass C = contracts, placements,
delivery_routes, route_stops, recall_notices, travel_authorizations routes. Each pass edits
`PRD_COMPLETED.md` in place; pass A creates it from `PRD_FINALIZED.md`.

Verbatim subagent summary follows.

---

## Result

`/home/ubuntu/github/CodingPRD/tasks/task_2575_home_oxygen_respiratory_therapy_service/workspace/PRD_FINALIZED.md` created as a **byte-identical copy** of `PRD.md`.

- PRD.md: 608 lines. PRD_FINALIZED.md: 608 lines. **Delta: 0 lines / 0.00%** (md5 `964b3f99466110415730d7919eb753f3` on both).
- **Changes: none.** Every item in `<step_7_diff>` traced to a pure test/fixture bug where PRD already uniquely determines the behavior and `implementation/` already complies.

## Per-item disposition

**Item 1 — `test_05_entity_contracts.py:1037`, `ERR_REPLACED_UNIT_NOT_REPLACEABLE` status code -> no edit.**
- Subject: HTTP status for `ERR_REPLACED_UNIT_NOT_REPLACEABLE`.
- Impl paths enumerated: `implementation/core.py:139` (`"ERR_REPLACED_UNIT_NOT_REPLACEABLE": 422`) — the single status map; `implementation/routes/equipment_units.py:67` — the sole raise site (fleet-unit registration, the only operation PRD attaches this error to). Also grepped for any other raise/override: none.
- PRD already pins it in two places, both matching impl: §5 table line 584 (`| ERR_REPLACED_UNIT_NOT_REPLACEABLE | 422 |`) and §2.10 ladder pos. 56 (line 201), with the substantive rule restated at §2.x line 245 and §3.x line 396. `test_helpers/api_errors.py:161` also already said 422. Pure test bug (a stray hardcoded `409` contradicting both PRD and the helper). Nothing was PRD-silent.

**Item 2 — `test_06_lifecycle_transitions.py:675`, equipment-assignment probe role -> no edit.**
- Subject: authorized-role list for `POST /home-oxygen/rental-contracts/{contract_id}/equipment-assignments`.
- Impl paths enumerated: `implementation/routes/contracts.py:332-335` (`authenticate((ROLE_THERAPIST,))`) — the endpoint itself; plus the parallel therapist-only endpoints so the wording would not be over-narrowed if touched: `routes/placements.py` release + malfunction, `routes/equipment_units.py` service, `routes/route_stops.py` complete-setup, `routes/patients.py` risk-reassessments; and `core.py` role-tuple constants / `LOGISTICS_READERS` for the read paths.
- PRD §4 line 494 already lists `RespiratoryTherapist` and only `RespiratoryTherapist` for that endpoint, and §2.10 pos. 3 already fixes `ERR_UNAUTHORIZED` above everything else. Impl matches exactly. Pure test bug (probe issued as `BRANCH_MANAGER`). Nothing was PRD-silent.

**Flagged non-issue A — `ERR_CYLINDERS_NOT_APPLICABLE` -> no edit, confirmed non-issue.** PRD §3.5 line 324 states the firing condition explicitly and unambiguously in prose ("supplying a non-zero cylinder count on a `PICKUP` or a `PORTABLE_REFILL` stop is rejected"), which matches `routes/route_stops.py:152` (`if stop_type in NO_CYLINDER_TYPES and data["cylinders_requested"]`) and the `0..6, default 0` field spec at `route_stops.py:72`. The ladder entry at pos. 74 is stated in the same pass-condition voice as the rest of the ladder. No ambiguity to pin.

**Flagged non-issue B — `ERR_NO_PLACED_EQUIPMENT` on a zero-cent post -> no edit, confirmed non-issue.** PRD §3.8 line 400 and ladder pos. 80 both require `monthly_allowable_cents > 0`; `routes/contracts.py:239-240` is `if contract["monthly_allowable_cents"] <= 0: raise ApiError("ERR_NO_PLACED_EQUIPMENT")`. Impl is the PRD-faithful side; the conflicting expectation lived only in SCAFFOLD (not read).

## Out-of-scope observations for Step 9 (deliberately NOT edited)

While running the mandatory pre-edit enumeration for item 2's guard chain I found ladder-order divergences that are **not** revealed by any `<step_7_diff>` item and are not reachable from either Step 7 test site. I left them alone rather than make a partial edit that could itself become a new mismatch — flagging them so Step 9's full scan can adjudicate them as a set:

- `routes/contracts.py:338-342` (equipment assignment) and `:397-400` (travel-supply) both check `ERR_CONTRACT_CLOSED` **before** `ERR_PATIENT_NOT_ACTIVE`, whereas PRD §2.10 puts `ERR_PATIENT_NOT_ACTIVE` at pos. 33 and `ERR_CONTRACT_CLOSED` at pos. 34. Observable only when a contract is `CLOSED` *and* its patient is `DISCHARGED` (reachable: close from `RETURNED`, then discharge). The two impl paths are consistent with each other, so a 33/34 swap would be globally safe on its own — but see the next two points, which interact.
- `routes/contracts.py:294-301` (`resume-billing`) enforces `ERR_PATIENT_NOT_ACTIVE`, an operation PRD ladder pos. 33 does **not** list ("Applies to six operations: ... equipment assignment and travel-supply requests").
- `routes/contracts.py:271-274` (month reversal) and `:295-298` (`resume-billing`) both raise `ERR_CONTRACT_CLOSED` **before** `ERR_INVALID_STATE`, whereas PRD puts `ERR_INVALID_STATE` at pos. 31, above pos. 34.

## Step 9: Complete PRD — 2026-09-03T19:52:00Z

Ran as three sequential file-partitioned passes (rationale recorded under Step 8). All three
edited `workspace/PRD_COMPLETED.md` in place; pass A created it from `PRD_FINALIZED.md`.

Orchestrator verification of the final artifact:
- `PRD_COMPLETED.md` = 609 lines / 150,754 chars vs `PRD_FINALIZED.md` 608 / 134,670
  (+1 line, +16,084 chars). md5 `06b1421441068fdb41832e685ce91b39` vs
  `964b3f99466110415730d7919eb753f3` — NOT byte-identical, so the scan genuinely ran
  (the byte-identical outcome is the tell that it did not).
- `diff` touches 89 lines; 47 edits total across the three passes.
- All five top-level sections present, §5 still last, file ends on
  `| \`ERR_NO_PLACED_EQUIPMENT\` | 422 |` — no truncation.
- Structure preserved: 80 ladder entries, 73 error rows, no renumbering.
- `find` confirms NO file under `implementation/`, `test_suite/` or `test_helpers/` is newer
  than `results.1.json` (19:05). Steps 8 and 9 touched only PRD files, so the verified
  8/8-round 157/157 sweep remains valid for the delivered implementation.

Edit totals by pass: A (shared layer) 12 ambiguity-pins + 4 mismatch-revisions = 16;
B (branches/patients/qualifying_tests/cmns/equipment_units/clock) 6 + 3 = 9;
C (contracts/route_stops/delivery_routes/recall_notices/placements/travel_authorizations)
14 + 8 = 22. Total 32 ambiguity-pins + 15 mismatch-revisions = 47.

Pass C resolved all four known §2.10 ladder-order divergences (plus two it found itself in
`route_stops.py`) by keeping the ladder numbering intact and adding scoped exception clauses
to entries 31/33/34, mirrored in the §3 prose — the minimal edit that makes PRD_COMPLETED.md,
read alone, yield the implementation's actual guard order.

### Pass A verbatim summary

PASS A (shared layer) complete. 608 lines / 134,670 chars -> 609 lines / 140,046 chars
(+1 line, +5,376 chars). 12 ambiguity-pins, 4 mismatch-revisions (14 diff hunks).

- §2.1 — revise — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as absent -> `ERR_UNAUTHENTICATED` — core.py:441
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` + exactly 20 uppercase-alphanumeric characters — core.py:392,396
- §2.2 (`api_request_timestamp`) — insert — ambiguity — read from the **logical clock**, not host time, so requests between advances share it — core.py:399-403
- §2.2 (error bullets) — insert — ambiguity — `message` wording non-contractual; unrouted path / unsupported method render the same envelope with `ERR_INVALID_REQUEST` under 404/405; trailing slashes tolerated — app.py:29,55-59
- §2.3 — insert — ambiguity — system-wide `created_at` tie-break is insertion order; undeclared and unparseable boolean filters are ignored, not rejected — core.py:381-386,495-504
- §2.4 — insert — ambiguity — `updated_at` equals `created_at` at first persist — core.py:361-370
- §2.6 — insert — ambiguity — the clock takes its new value *before* the sweep, so swept rows stamp `updated_at` with the new instant; certificates swept in `created_at` order — domain.py:250-273, routes/clock.py:33-35
- §2.8 P1 — insert — ambiguity — 2-dp values emitted as JSON numbers (45.00 -> `45.0`); `prescribed_lpm`/`max_continuous_lpm` range-checked only, echoed exactly as supplied — core.py:328-332, validate.py:88-96, serial.py:71,133
- §2.8 last bullet — insert — ambiguity — accepted inbound instant grammar (Z / numeric offset normalised to UTC / no zone = UTC / space for `T`), non-parsing -> `ERR_INVALID_REQUEST`; dates and months strict — core.py:254-309
- §2.10 pos. 17 — insert — ambiguity — also covers declared string lengths, formats (`state_code`, NPI), array item types; explicit `null` on a non-nullable field fails here even when a default exists; absent/malformed/non-object body treated as `{}` — validate.py:53-61,101-149
- §2.10 pos. 18 — insert — ambiguity — enumerated fields judged on set membership alone, so a wrong-typed value for an enum field reports `ERR_INVALID_ENUM_VALUE`, not `ERR_INVALID_REQUEST` — validate.py:123-124,150-163
- §3.4 eligibility filter — revise — mismatch — flow comparison is exact-decimal, not "at one decimal place" — calc.py:345
- §3.5 `sequence_index` — insert — ambiguity — only stops whose index actually changes are re-versioned — domain.py:154-161
- §3.7 (unit service / retire) — revise — mismatch — `RETIRED` excluded from the two frozen snapshots only; the live `remediated_unit_count` recount ignores status — calc.py:450-460 vs routes/recall_notices.py:73
- §3.8 cap-summary — insert — ambiguity — candidate month null when the contract has neither posted nor first service month; both positions and effective report 0, `months_remaining` = full cap limit — calc.py:174-203
- §3.9 travel denial — revise — mismatch — `denial_reason` validated but never persisted, absent from the representation — serial.py:228-250 vs routes/travel_authorizations.py:32

Verified as already pinned: the 73-entry `ERROR_STATUS` map matches the §5 table exactly
(programmatic diff, zero divergences); the five reader role tuples match every §4 authorized-role
list; pagination defaults/bounds/`has_more`/`total_count`; `CLOCK_START`; `add_months` clamping;
all eleven calculations' formulas, rounding order and boundaries; every serializer field list
except `denial_reason`.

### Pass B verbatim summary

609 lines before -> 609 after; 140,046 -> 141,679 chars (+1,633). 6 ambiguity-pins, 3 mismatch-revisions.

- §2.4 — insert — ambiguity — an update endpoint whose declared fields are all optional still counts as a mutation when the body supplies none of them (`updated_at` refreshed, `version`++); covers the three PATCH endpoints — routes/branches.py:96, routes/patients.py:148, routes/cmns.py:188
- §2.6 — insert — ambiguity — a single clock advance is unbounded above; the only shape rule on `to_iso8601` is that it parse as an instant — routes/clock.py:23,32
- §2.7 — insert — ambiguity — `expected_patient_version` declared as an integer >= 0, so a negative/non-integer value is a position-17 shape fault, not `ERR_STALE_PATIENT_VERSION` — routes/cmns.py:71
- §3.2 — insert — ambiguity — the patient demographic/mobility update carries no lifecycle precondition (works in `TRANSFER_PENDING` and `DISCHARGED`) — routes/patients.py:140-149
- §3.3 (score) — revise — mismatch — the documentation score is also recomputed **at approval**, and every recomputation is persisted *before* the threshold is judged, so a refused submit/approve leaves the new score on the row with no `version`/`updated_at` change — routes/cmns.py:206,242 + 95-100
- §3.3 (submission) — revise — mismatch — submission has **three** preconditions, not four, judged patient-`ACTIVE` -> staleness -> score; the study's group is not re-examined at submit (only at draft, ladder pos. 45) — routes/cmns.py:194-207
- §3.3 (correction) — insert — ambiguity — `correction_notes` is a required string with no length bounds, so an empty string is accepted, in contrast to the non-empty `void_reason` — routes/cmns.py:82 vs :84
- §3.6 (reassessment) — insert — ambiguity — the surveillance reassessment takes no request body and has no lifecycle precondition — routes/patients.py:174-179
- §3.7 (service) — revise — mismatch — the PM restamp example said "default 180-day interval"; the declared default is 365 — routes/equipment_units.py:46,129

Verified-and-left-alone: every authorized-role list for the 24 endpoints matches §4 exactly;
every guard chain in these modules follows the §2.10 ladder order exactly (notably
equipment_units 20->26->30->56->75 and cmns create 21->22->27->33->45->50, approve
SoD-before-state); qualifying-test immutability/derived outputs; discharge cascade order and
single patient `version`++; transfer open/complete/cancel field semantics.

### Pass C verbatim summary

609 lines / 150,754 chars (before 609 / 141,679 -> +9,075 chars, 0 lines; every edit in-paragraph).
Structure intact: 25 headings, 80 ladder entries, 73 error-table rows. Pass A and pass B edits
verified still present. **22 edits: 14 ambiguity-pins, 8 mismatch-revisions.**

- §2.7 — insert — ambiguity — `expected_contract_version` pinned as an integer no smaller than 0, so a negative/non-integer value is a shape fault at ladder pos. 17, not a stale read — routes/contracts.py:380
- §2.10 entry 31 — revise — mismatch — scoped exception clause: month reversal and billing resumption report `ERR_CONTRACT_CLOSED` (pos. 34) first; stop creation's PICKUP-needs-`PLANNING` check is evaluated last of all stop-creation guards (below 36, 38, 48, 49, 54, 60, 61, 62, 74); setup completion's `PENDING_SETUP` and reserved-placement checks are evaluated after 37 and 39 — routes/contracts.py:271,295, routes/route_stops.py:154,266,272
- §2.10 entries 33 & 34 — revise — mismatch — entry 33's operation list corrected from six to **seven** (billing resumption added); reciprocal notes on 33/34 that equipment assignment and travel-supply requests evaluate 34 before 33 — routes/contracts.py:294-301,338-342,397-400
- §3.4 — revise — mismatch — equipment-assignment guard sentence reordered so the closed-contract guard is stated and judged first (pos. 34), then the patient checks, then the CMN check — routes/contracts.py:338-348
- §3.4 — insert — ambiguity — release-placement requires only that the placement be `RESERVED`: no unit precondition, no contract-state precondition (releasable on a CLOSED contract), unit moved only if still `RESERVED`, version +1 on placement and contract always but on the unit only when it moved — routes/placements.py:65-85
- §3.5 — insert — ambiguity — a freshly created stop is exempt from the renumber-touch rule: persisted at its assigned position, returned at `version` 1 with `updated_at == created_at` — routes/route_stops.py:89-97,183
- §3.5 — revise — mismatch — a PICKUP stop is rejected with `ERR_INVALID_STATE` on a `LOCKED` route, evaluated last of all stop-creation guards; the `IN_SERVICE -> PICKUP_SCHEDULED` move is conditioned on the contract actually being `IN_SERVICE` — routes/route_stops.py:154-156,185-187
- §3.5 — insert — ambiguity — generic completion's pickup cascade is conditioned on `PICKUP_SCHEDULED`, and generic completion does not re-derive the route's stored roll-ups at all; the route's `version` moves only if this completion bubbles it up — routes/route_stops.py:233-248
- §3.5 — insert — ambiguity — a miss leaves `refill_slots_used` unchanged, bumps route `version` by exactly 1, and has no stop-type restriction — routes/route_stops.py:334-351
- §3.6 — insert — ambiguity — `education_topics_covered` nullable with no default: omitted, explicit `null` and `[]` all accepted and all persist as `[]` — routes/route_stops.py:79-86,286
- §3.6 — revise — mismatch — the reserved-placement precondition is enforced **only on the no-smoking branch**; a smoking report is accepted with no reserved placement; both that failure and the `PENDING_SETUP` failure report `ERR_INVALID_STATE` after the dispatched-route and stop-type checks — routes/route_stops.py:265-273
- §3.6 — insert — ambiguity — hop two's billing branch fires only from `ACCRUING`/`CAP_REACHED`; an already-`SUSPENDED` contract keeps its state and its existing `suspension_reason` — routes/route_stops.py:296-298
- §3.7 — insert — ambiguity — `model_code` pinned as a required 1-40-char string with no format rule, matched by exact equality; a zero-match code is still a valid notice (both snapshots 0, closable immediately) — routes/recall_notices.py:40,45-50
- §3.7 — insert — ambiguity — `oxygen_gap_minutes` is a required integer >= 0 with no upper bound; `ERR_INVALID_STATE` judged after request shape — routes/placements.py:87-95
- §3.7 — insert — ambiguity — the live remediated recount is read-time only: servicing a unit is not a write against the notice row (`updated_at`/`version` untouched); only acknowledgement and closure mutate it — routes/recall_notices.py:6,155, serial.recall_notice_out
- §3.7 — insert — ambiguity — recall hop-four boundaries: already-`SUSPENDED` contract keeps its prior reason but is still recomputed and versioned; already-`CLOSED` contract skipped outright; each contract visited exactly once — routes/recall_notices.py:103-111
- §3.8 — revise — mismatch — reversal judges `CLOSED` before the origin-state check and reports `ERR_CONTRACT_CLOSED`; `SUSPENDED` gives `ERR_INVALID_STATE`; the post-removal cap candidate month is the largest remaining `service_month`, or `first_service_month` when the ledger empties — routes/contracts.py:269-284
- §3.8 — revise — mismatch — resume-billing judges the closed check first (`ERR_CONTRACT_CLOSED`, ahead of the origin-state check) and enforces `ERR_PATIENT_NOT_ACTIVE` ahead of the CMN check; the candidate month matches the cap-summary read, with null -> position 0 -> resumes to `ACCRUING` — routes/contracts.py:294-312
- §3.8 — insert — ambiguity — `variant_applied` pinned to exactly `SERVICE_MONTH_BASIS` / `PAID_MONTH_BASIS` — routes/contracts.py:186-215
- §3.9 — insert — ambiguity — travel approval: either contract condition failing reports `ERR_INVALID_STATE`, both judged before the hold check — routes/travel_authorizations.py:65-76
- §3.9 — insert — ambiguity — travel `receiving_branch_id` nullable, defaults to null, but `min_len=1` when supplied, so `""` is a shape fault — routes/contracts.py:383
- §3.9 (~line 451) — revise — mismatch — dead prose about a transfer pulling equipment replaced: a transfer never disturbs home equipment (`receiving_branch_id` is required on transfer requests, so the branch is never unresolved); `TRANSFER` in placement `removal_reason` and unit `quarantine_reason` is declared for completeness but never written — the only `TRANSFER` any operation writes is a contract's `suspension_reason` — routes/patients.py:186,194

Ladder divergences: all resolved by keeping the ladder numbering intact and adding scoped
exception clauses to entries 31/33/34, mirrored by inline §3 prose, each verified in code rather
than trusted from the brief. Two additional divergences found by pass C itself
(route_stops.py:154-156 and 265-273) were folded into the same clauses.

Deliberately left unpinned — unreachable code paths, which PRD prose cannot describe without
inventing behavior: `create_assignment`'s `get_branch` `ERR_BRANCH_NOT_FOUND`;
`report_malfunction`'s and `approve_authorization`'s `contract is None` fallbacks;
`prorated_amount_cents`'s `days < 0` clamp; `route_manifest`'s missing-branch fallback;
`create_stop`'s null-patient path; and the unreachable `CAP_REACHED` + `PENDING_SETUP`
state combination.

---

## PIPELINE COMPLETE — 2026-09-03T19:52:00Z

All nine steps done. Final state: 157 tests, 8/8 sweep rounds at 157/157 (0 failed, 0 skipped,
0 tests deleted across the whole pipeline), and `workspace/PRD_COMPLETED.md` written.
