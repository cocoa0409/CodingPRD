# Worklog — task_2696_transit_fare_enforcement_proof_of_payment

## Step 1: Create task directory — 2026-09-04T08:12:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2696_transit_fare_enforcement_proof_of_payment` and its `workspace/` subdirectory. Index 2696 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T09:48:00.000Z

Scaffold generation for task 2696 is complete and lint-clean.

## Files

| File | Lines |
|---|---|
`/home/ubuntu/github/CodingPRD/tasks/task_2696_transit_fare_enforcement_proof_of_payment/SCAFFOLD.yaml` | 3123 |
`/home/ubuntu/github/CodingPRD/tasks/task_2696_transit_fare_enforcement_proof_of_payment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2640 |
`/home/ubuntu/github/CodingPRD/tasks/task_2696_transit_fare_enforcement_proof_of_payment/SCAFFOLD_CORNER_DESIGN.yaml` | 3937 |

All three parse with `yaml.safe_load`. `SCAFFOLD.yaml` has 13 top-level keys and contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; each design file has exactly one top-level key.

## SCAFFOLD.yaml counts (§1.0–§1.7)

- 14 entities (FareZone, TransitLine, ZoneLineAssignment, SignageAudit, Inspector, Rider, InspectionDeployment, InspectionEncounter, Citation, PenaltyPayment, AdjudicationHearing, Appeal, PaymentPlan, CommunityServiceAssignment)
- 9 state machines over 8 entities (Citation carries two parallel dimensions: `adjudication_status` 9 transitions, `settlement_status` 10)
- 2 concurrency rules (OCC on `Citation.version` via `expected_citation_version` on `POST /payment-plans` and `POST /community-service-assignments`)
- 14 calculations, 56 ordered validations, 59 endpoints, 65 error codes, 6 roles (`FareInspector`->Inspector and `Rider`->Rider are `entity_backed`; the other four are `opaque`); archetype compliance_audit + ledger_reconciliation, layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers, `role_model: segregation_of_duties`, `consistency_model: immediate`

## Design index instance counts

- §1.8 `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: **25** instances across all nine §0.5 rules (dual_variant_calc 3, combinatorial_formula 4, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2)
- §1.9 `SCAFFOLD_CORNER_DESIGN.yaml`: **81** instances — entities 11, state_machines 15, calculations 16, validations 16, endpoints 5, errors 8, rbac 5, cross_cutting_layers 5, consistency_model 1 (55 full recipes + 26 `excluded_because` stubs that each cite a §1.8 instance verbatim). All 106 instance names are unique across both files; all `grounds` references resolve into §1.1–§1.7; all 65 error codes are triggered by at least one §1.8/§1.9 instance.

Notable design fix made while closing error coverage: §1.4 priority 18's `check` now states that `SERVICE_ACTIVE` also passes on `POST /payment-plans` (the alternative is adjudicated later by priority 37), which makes `ERR_ALTERNATIVE_ALREADY_ACTIVE` reachable — it previously could never fire. `ERR_APPEAL_ROUND_LIMIT` needed a second pass through the supplement cycle (request-supplement -> resubmit -> request-supplement -> resubmit) and got its own errors instance.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2696_transit_fare_enforcement_proof_of_payment/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2696_transit_fare_enforcement_proof_of_payment/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2696_transit_fare_enforcement_proof_of_payment/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1201

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy shared files — 2026-09-04T09:50:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T10:06:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **454 lines**, built with 1 `Write` + 8 incremental `cat >>` heredoc appends (no truncation).

**Section list**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-identical `cat` of the canonical `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Record Identity, Timestamps and Revision Counters · 2.5 The Logical Clock and Temporal Windows · 2.6 Path Resolution and Reference Integrity · 2.7 Money, Basis Points and Rounding Discipline · 2.8 Version Pinning on Settlement Writes · 2.9 Cascade Discipline · 2.10 Validation Precedence
- `## 3. Business Logic & Workflows` — 3.1 Designating a Proof-of-Payment Zone · 3.2 The Line Network, the Inspector Roster and the Rider Registry · 3.3 Planning, Activating and Closing a Sampled Deployment · 3.4 The Inspection Encounter: Fare Media Validation and Identity Handling · 3.5 Citation Issuance and the Progressive Penalty Ladder · 3.6 Administrative Adjudication, Dismissal and Reissuance · 3.7 Appellate Review · 3.8 Settling a Balance: Direct Payment, Installment Plans and Community Service · 3.9 Equity Distribution and Revenue Recovery Analytics (9 subsections, within the 5-9 range)
- `## 4. Endpoint Definitions` — 4-column table, 59 rows
- `## 5. Error Code Catalogue` — 2-column table, 65 rows

**Tail confirmed complete:** file ends on the final §5 table row `| ERR_NOTHING_OUTSTANDING | 422 |` — a complete row at a real section boundary, no mid-sentence cut.

**Hard Contract 1 — Field-Name Coverage: PASS** (two independent passes; the second used strict exact-token matching after stripping fenced code blocks)
- entity `fields[].name`: 109/109 present · non-GET `input` identifiers: 57/57 · GET `query_params`: 23/23 · report `output` keys: 17/17 · `path_params`: 1/1 (`id`) · roles: 6/6. Diff `required - actual` empty in both passes.

**Hard Contract 2 — Rule Coverage: PASS**
- All 56 validation `error_id`s (including the 20 pipe-alternated not-found ids in priorities 6 and 7) appear in §1-§3 prose, not only in the §5 table.
- Both `concurrency_rules` covered: `expected_citation_version` pinning -> `ERR_STALE_CITATION_VERSION` / 412 on plan and community-service creation.
- All 9 state machines: every `from`/`to` state token present in prose (0 missing), including Citation's parallel `adjudication_status` x `settlement_status` dimensions.
- All 14 calculations described in prose; sibling-branch symmetry verified for the three dual-variant calcs — `offense_sequence` vs `citation_only_sequence`, `measured_evasion_rate_bps` vs `resolved_evasion_rate_bps`, `ACCRUAL` vs `CASH` basis — both branches written.
- All calculation constants accounted for; only `BASE_TIER_CENTS` lacks a literal map form because it is rendered as prose tiers (7500 / 15000 / 25000 all present).
- 31 endpoints with `side_effects` covered by the cascade narratives (§2.9, §3.1, §3.3, §3.6).
- Zero pseudocode operators and zero fuzzy words in the file.

**Hard Contract 3 — §3 Path Purity: PASS** — 297 distinct backticked tokens in §3; zero start with `/`, zero are a bare HTTP method, zero combine method+path.

**Cross-check of §4/§5 against the scaffold:** all 59 (method, path) pairs match exactly, no extras or omissions; authorized-role sets match the scaffold's `roles` for every endpoint; all 65 error ids present with matching HTTP statuses.

Both hard constraints honored: neither design index was opened, grepped, or referenced; no sibling task directory was read.

**Orchestrator truncation check (independent):** `wc -l` = 454; headings enumerate §1-§5 with all 10 §2 subsections and all 9 §3 subsections present; `tail -25` ends on a complete error-table row. §3 body is 67,320 chars across 175 dense lines. 49 of the 65 error ids appear inside §3 itself, the remainder inside §2's precedence / RBAC / not-found prose. Not truncated — accepted without regeneration.

## Step 6: Generate implementation — 2026-09-04T10:40:00.000Z

Implementation complete and smoke-verified.

## Files written
`workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` (executable) | 10 |
| `requirements.txt` | 1 |
| `core.py` — 66-id error catalog, envelope, logical clock, empty `Store`, auth/RBAC, pagination, schema validators | 521 |
| `calc.py` — all constants/enums + 13 calculations (penalty tiers, admin-fee bands, installment schedule, service credit, deployment counters) | 343 |
| `serial.py` — 14 serializers with computed-on-read fields | 257 |
| `cascade.py` — payment ledger append, zone-suspension / zone-revocation / dismissal-unwind cascades | 101 |
| `routes_zones.py` | 332 |
| `routes_deployments.py` | 312 |
| `routes_citations.py` | 335 |
| `routes_appeals.py` | 202 |
| `routes_settlement.py` | 340 |
| `routes_reports.py` | 157 |
| `app.py` — blueprint registration + ApiError/HTTPException/Exception handlers | 63 |

Total 2974 lines. All files present, non-empty, `py_compile` clean, `__pycache__` removed.

## Endpoint coverage
**59/59.** A programmatic diff of Flask's `url_map` against the PRD §4 endpoint table (method + path, placeholders normalized) is an exact set match — zero PRD-only routes, zero implementation-only routes.

## Smoke test (PORT=18696, killed by PID only; no broad pkill)
Happy paths verified end to end: zone DRAFT->PENDING_SIGNAGE->DESIGNATED with signage recompute; line/assignment/inspector/rider; deployment PLANNED->ACTIVE->CLOSED (cost 86400, sample_adequacy 1.0, evasion rates in bps); encounters (NO_PROOF, EXPIRED, WARNING_ISSUED); citation money 7500+600 fee, escalation to tier 2/3 with cap; direct payment; OCC 412; payment plan (down 710 / financed 6390 / 2130x2 + 2130 final) through 3 installments to COMPLETED + SATISFIED; contest -> hearing +14d; hearing REDUCE 15000->10000 with fee re-derivation (1800->800) and floor 7500 enforced; appeal file -> segregation 403 for the deciding officer -> request-supplement -> resubmit (round 2) -> `ERR_APPEAL_ROUND_LIMIT` -> GRANTED with dismissal-unwind (DISMISSED/WRITTEN_OFF, balance 0); reissue inheriting `issued_at`; community service (required_hours ceil, `hours:0` -> 422, capped credit 13800 -> COMPLETED + SATISFIED); plan default via assess-delinquency (missed 2 -> DEFAULTED, citation back to OUTSTANDING); `ERR_ALTERNATIVE_ALREADY_ACTIVE` when superseding a live service assignment with the flag false, and successful supersede (assignment -> FORFEITED) with the flag true; both reports (equity groups with 4-dp string rates and disparity index; revenue-recovery ACCRUAL vs CASH with `recovery_ratio_bps`); pagination bounds (`limit=0`/`limit=101` -> `ERR_INVALID_REQUEST`), filters, unauth 401, RBAC 403, 404/405 envelopes, clock set/echo.

Fresh-boot check (relevant to `--isolation per-test-server`): after a kill/relaunch every list endpoint returns `total_count: 0` with an empty array and the clock resets to `2026-08-01T00:00:00Z` — storage is in-memory dicts only, with no seeding, preloading, or hardcoded entities anywhere.

Two apparent smoke failures were script bugs, not implementation bugs: an invalid `mode` enum value (`BUS_RAPID`) and probing non-existent paths (`/zones`, `/deployments`); the PRD prefixes are `/fare-zones`, `/inspection-deployments`, `/inspection-encounters`, `/adjudication-hearings`. Also confirmed correct: community service refuses `PLAN_ACTIVE` with `ERR_SETTLEMENT_STATUS_INVALID` (PRD line 296 — no superseding path *into* service), so `ERR_ALTERNATIVE_ALREADY_ACTIVE` is reachable only on `POST /payment-plans`.

Port 18696 is free; no server processes of mine remain.

## Step 5: Generate unit tests — 2026-09-04T11:25:00.000Z

Test suite generation for task 2696 is complete.

## Files written

`test_helpers/` — 9 files, 2,357 lines
`__init__.py` 16 · `api_client.py` 270 (59 endpoint methods) · `api_errors.py` 167 (65 error ids + HTTP status map) · `assertions.py` 299 · `constants.py` 288 · `factories.py` 305 · `fixtures.py` 605 · `test_users.py` 115 · `types.py` 292

`test_suite/` — `conftest.py` (19) + 18 test modules, 6,302 lines
Queue A: `test_01_dual_variant_calc.py` 314/7 · `test_02_combinatorial_formula.py` 419/8 · `test_03_non_linear_state_machine.py` 278/6 · `test_04_transitive_cascade.py` 364/7 · `test_05_priority_pair_validation_conflict.py` 352/7 · `test_06_boundary_precision_check.py` 330/8 · `test_07_cross_entity_state_dependency.py` 323/8 · `test_08_resource_temporal_overlap.py` 226/4 · `test_09_compensating_invariant.py` 304/7
Queue B: `test_10_entities.py` 409/11 · `test_11_state_machines.py` 235/7 · `test_12_calculations.py` 340/7 · `test_13_validations.py` 672/9 · `test_14_endpoints.py` 317/5 · `test_15_errors.py` 681/8 · `test_16_rbac.py` 412/5 · `test_17_cross_cutting_layers.py` 224/2 · `test_18_consistency_model.py` 102/1

## Coverage tally

- **117 tests collected** (`pytest --collect-only` clean), 117 `Design:` tags — exactly one per test, zero untagged, zero dual-tagged, zero tags resolving to a non-existent or stub instance.
- **Queue A: 25/25 instances, 62 tests.** Every instance has >=2 tests (distribution 2x15, 3x8, 4x2), and every `Design: Difficulty/<rule_id>/<name>` pair matches the yaml's own rule grouping.
- **Queue B: 55/55 non-stub instances, 55 tests** (one each), sections `entities` 11, `state_machines` 7, `calculations` 7, `validations` 9, `endpoints` 5, `errors` 8, `rbac` 5, `cross_cutting_layers` 2, `consistency_model` 1. All 26 `excluded_because:` stubs verified — every `difficulty_instance:` pointer resolves to a real name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`; none translated.
- No instance was skipped outright: all 25 + 55 are covered. `pyflakes` clean except three intentional side-effect imports. No `skip`/`xfail`/mocking anywhere; no scaffold references in prose.

## Design/PRD conflicts resolved PRD-first (asserted outcome changed or narrowed)

1. `Difficulty/transitive_cascade/appeal_grant_cascades_four_links_...` — design's `grounds_code: SIGNAGE_DEFECT` / `dismissal_reason_code: SIGNAGE_DEFICIENCY` are not enum members; used `SIGNAGE_DEFICIENCY` / `SIGNAGE_DEFICIENT`.
2. Both `Difficulty/resource_temporal_overlap` instances use `sampling_method: RANDOM_INTERCEPT` and `mode: BUS_RAPID`, neither a PRD enum; substituted `CLUSTER_RANDOM` / `BUS`. No effect on the asserted outcome.
3. `Corner/entities/fare_zone_creation_stamps_defaults_and_system_fields` asserts `max_concurrent_deployments == 1`; PRD §3.1 says it defaults to 2 — asserted 2.
4. `Corner/calculations/signage_compliance_rounds_half_up_...` asserts zone `version == 3`; PRD does not uniquely derive that figure — that one sub-assertion omitted (condition 2).
5. `Corner/state_machines/revoked_zone_cannot_be_resubmitted_for_signage` asserts a literal post-revoke `version == 5`; asserted instead that the version is unchanged from the captured post-revoke value (condition 2).
6. `Corner/endpoints/reissue_is_allowed_only_inside_the_window_...` asserts the reissue's `issued_at == 2026-08-19T09:00:00Z`; PRD line 258 says the reissue **inherits** the original `issued_at` — asserted `2026-08-05T09:00:00Z` and `contest_deadline_at 2026-09-04T09:00:00Z`.
7. `Corner/errors/a_third_resubmission_hits_the_appeal_round_limit` asserts the *second* `request-supplement` succeeds (200) and the second resubmit earns `ERR_APPEAL_ROUND_LIMIT`. PRD line 268 bounds **both** the supplement request and the resubmission at `round_index < 2`, so the design's shape is unreachable; the instance's core claim was preserved by asserting `ERR_APPEAL_ROUND_LIMIT` (409) on the second `request-supplement`, guarded with `!= ERR_APPEAL_STATUS_INVALID`.

Also of note: the `Corner/errors` not-found instance deliberately probes only 11 of the PRD's 12 not-found codes (omitting `ERR_CITATION_NOT_FOUND`); the design was followed as written.

**Orchestrator layout check:** `test_helpers/` and `test_suite/` are both at the task root (not under `workspace/`); `workspace/` contains only INSTRUCTION.md, PRD.md and implementation/. No relocation needed.

## Step 7: Run tests and iterate — 2026-09-04

Three parallel 8-round sweeps (`--isolation per-test-server`, `--test-timeout 30`). Final state: **117/117 in all 8 rounds**, zero flakiness observed across the three sweeps.

### Iteration 1 — 8/117 in all 8 rounds
Single upstream fixture bug: every zone code in the suite was a 2-character literal (`"Z1"`, `"Z2"`, `"Z3"`, `"Z9"`), but PRD line 146 requires `zone_code` "between 3 and 32 characters long". 107 tests died as `Setup step failed with HTTP 400: ERR_INVALID_REQUEST - Field 'zone_code' must be at least 3 characters`, plus 2 more asserting on the same 400 directly. The implementation's `min_len=3` guard (`routes_zones.py:27`) is PRD-required, so this was a test bug. Renamed `Z<n>` -> `ZN<n>` across `test_suite/` and `test_helpers/` (31 literals), which preserves every zone-code equality/inequality relation the `WRONG_ZONE` verdict tests depend on. Verified `zone_code` is the only field in the system with a minimum length above 1.

### Iteration 2 — 114/117 in all 8 rounds (3 deterministic failures)

1. `test_11_state_machines.py::test_a_planned_deployment_and_a_new_encounter_open_in_their_declared_states` — `KeyError: 'citation_id'`. The test asserted `encounter["citation_id"] is None`. **PRD is silent**: the reference runs the other way (a citation carries `encounter_id`, PRD line 80); no PRD sentence puts a `citation_id` on `InspectionEncounter`, and the field is absent from the entity's field list in §3.4. Removed that single uncovered assertion under the partial-coverage rule (the test's other assertions — `outcome PENDING`, `validation_result`, the deployment's initial counters — are all verbatim in PRD lines 201/47-49 and were kept). Also dropped the phantom `citation_id` key from the `InspectionEncounter` TypedDict in `test_helpers/types.py`.

2. `test_12_calculations.py::test_partial_direct_payments_subtract_exactly_and_the_remainder_satisfies` — `KeyError: 'amount_paid_cents'`. The test read `amount_paid_cents` / `outstanding_balance_cents` / `settlement_status` — all *citation* fields — straight off the 201 response of `POST /citations/{id}/payments`, which PRD §4 line 357 defines as applying a payment (the implementation returns the created ledger row). Test bug: inserted a `read_citation` after each partial payment and asserted against the citation. No assertion weakened.

3. `test_17_cross_cutting_layers.py::test_a_plan_on_a_stale_citation_view_is_refused_and_the_retry_prices_the_moved_balance` — `assert 7720 == 6720`. Test arithmetic error. The balance identity (PRD line 236) is `total_due_cents - amount_paid_cents - service_credit_cents`; with `total_due 9720` and `amount_paid 2000` (1000 direct + 1000 down payment, both asserted in the same test) the outstanding balance is 7720. The test's own inline comment and its `financed_cents == 7720` assertion already agreed with 7720. Corrected the expectation to 7720; the implementation was right.

### Iteration 3 — 117/117 in all 8 rounds
`results.1..8.json`: 117/117, 117/117, 117/117, 117/117, 117/117, 117/117, 117/117, 117/117.

**No implementation change was made in Step 7** — all three iteration-2 defects and the iteration-1 wipeout were test-side. No test was deleted, no `skip`/`xfail` added, no `error_id` assertion downgraded to an HTTP-status assertion; test count is unchanged at 117.

## Step 7: Run tests and iterate — 2026-09-04T11:55:00.000Z

(Orchestrator-recorded verbatim subagent summary; the subagent also appended its own per-iteration notes above.)

All 8 rounds green at 117/117. Every defect was test-side; the implementation was not modified.

## Iterations run: 3

**Iteration 1 — 8/117 in all 8 rounds.** One upstream fixture bug caused a near-total wipeout: every zone code in the suite was a 2-character literal (`"Z1"`, `"Z2"`, `"Z3"`, `"Z9"`), but PRD line 146 requires `zone_code` "between 3 and 32 characters long". 107 tests died as `Setup step failed with HTTP 400: ERR_INVALID_REQUEST - Field 'zone_code' must be at least 3 characters`, plus 2 asserting on that 400 directly.

**Iteration 2 — 114/117 in all 8 rounds**, 3 deterministic failures.

**Iteration 3 — 117/117 in all 8 rounds.**

## Tests deleted: none
No test failed the PRD-coverage or unique-derivability gate outright. One test had a single uncovered *assertion* removed under the partial-coverage rule (STEP 1c):

- `test_11_state_machines.py::test_a_planned_deployment_and_a_new_encounter_open_in_their_declared_states` — dropped `assert encounter["citation_id"] is None`. **PRD-silence category: field not a declared entity attribute.** The reference runs the other direction (a citation carries `encounter_id`, PRD line 80); no PRD sentence puts a `citation_id` on `InspectionEncounter`, and it is absent from the entity's field list in §3.4. The test's other assertions (`outcome PENDING`, `validation_result`, the deployment's zeroed counters and `sample_adequacy_ratio`) are verbatim in PRD and were kept.

## Fixes to `test_helpers/`
- `test_helpers/fixtures.py`, `test_helpers/factories.py` — `register_zone` / `fare_zone_payload` default `zone_code` widened `"Z1"` -> `"ZN1"`; PRD requires >=3 characters. Applied as a consistent `Z<n>` -> `ZN<n>` rename across all 31 literals in both directories so every zone-code equality/inequality relation the `WRONG_ZONE` verdict tests rely on is preserved. Confirmed `zone_code` is the only field in the system with a minimum length above 1.
- `test_helpers/types.py` — removed the phantom `citation_id` key from the `InspectionEncounter` TypedDict; not a PRD (or even scaffold) field.

## Fixes to `test_suite/`
- `test_12_calculations.py::test_partial_direct_payments_...` — the test read `amount_paid_cents` / `outstanding_balance_cents` / `settlement_status` (all *citation* fields) off the 201 response of `POST /citations/{id}/payments`, which PRD §4 line 357 defines as applying a payment; the implementation correctly returns the created ledger row. Added a `read_citation` after each partial payment and asserted against the citation. No assertion weakened.
- `test_17_cross_cutting_layers.py::test_a_plan_on_a_stale_citation_view_...` — test arithmetic error. PRD line 236's identity is `total_due_cents - amount_paid_cents - service_credit_cents`; with `total_due 9720` and `amount_paid 2000` (1000 direct + 1000 down payment, both asserted in the same test) the balance is 7720, not 6720. The test's own inline comment and its `financed_cents == 7720` assertion already agreed with 7720.

## Fixes to `implementation/`: none
All four defects traced to the test artifact. No PRD-required check was removed or weakened, no `skip`/`xfail` added, no `error_id` assertion downgraded to an HTTP-status assertion. Test count unchanged at 117 collected.

## Final per-round figures (from `workspace/implementation/results.$i.json`)
`117/117` in rounds 1, 2, 3, 4, 5, 6, 7 and 8 — zero flakiness across the final sweep, and the three earlier sweeps were likewise identical round-to-round (8/117 x8, then 114/117 x8), so no timing-sensitive behavior surfaced.

**Orchestrator independent verification:** all 8 `results.$i.json` exist (timestamped 11:52, ~35 KB each) and each parses to `passed=117 total=117 failed=0`. The clean sweep is real, not claimed.

**Step 8 gate decision:** the skip condition (0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes) is NOT met — Step 7 applied 2 `test_helpers/` fixes, 2 `test_suite/` fixes and 1 partial-coverage assertion removal. Step 8 therefore runs. Note for Step 8: the `implementation/` fix count is zero, so most items are pure fixture/arithmetic bugs with no PRD implication; the one genuine PRD-silence candidate is what `POST /citations/{id}/payments` returns in its 201 envelope (the ledger row vs the updated citation), and secondarily whether `InspectionEncounter` exposes a `citation_id`.

## Step 8: Finalize PRD — 2026-09-04T12:00:00.000Z

Done. `PRD_FINALIZED.md` written with two inline sentence insertions; no other diff item had a PRD implication.

**Line counts:** PRD.md 454 lines -> PRD_FINALIZED.md 454 lines (0.0% line delta; 2 lines revised in place, both edits inline).

**Changes**
- §4 (endpoint preamble, response-envelope default) — insert — pins that `POST /citations/{id}/payments` and `POST /payment-plans/{id}/installments` return **201 Created** with the created `PenaltyPayment` ledger row in `data`, not the citation or the plan — `implementation/routes_settlement.py:66` and `:184` (both `respond_object(serial.payment_out(payment), 201)`), row shape at `implementation/serial.py:247`.
- §3.4 (encounter fork paragraph) — insert — pins that the encounter<->citation link lives only on the citation's `encounter_id`, and that no citation identifier is among the encounter's fields — `implementation/serial.py:131` (`encounter_out` field list), record creation at `implementation/routes_deployments.py:237`.

**Per-edit pre-edit search log**

Edit 1 — subject: what the 201 envelope of a ledger-appending payment POST contains.
(b) Paths enumerated: `routes_settlement.py:33` `pay_citation` (201 `payment_out`), `:152` `pay_installment` (201 `payment_out`), `:73` `open_plan` (201 `plan_out`, though it appends a `DOWN_PAYMENT` row via `cascade.append_payment`), `:242` `open_service` (201 `service_out`), `:290` `log_hours` (200 `service_out`, though it appends a `SERVICE_CREDIT` row), `:187` `assess_delinquency` (200 `plan_out`), `cascade.append_payment` / `dismissal_unwind` (append `DISMISSAL_REVERSAL` rows with no response of their own), plus every other 201 site (`routes_zones.py:55,178,207,242,290,324`, `routes_deployments.py:106,254`, `routes_citations.py:111,189,224`, `routes_appeals.py:72`) — all of which return their own primary resource, so the existing default sentence stays true for them. Read `serial.payment_out`, `core.base_record`.
(c) Adjustment: the first draft said "the two calls that post to the penalty ledger", which would have been a false universal — plan opening, hour logging and the dismissal cascades also append ledger rows yet return the plan / assignment / nothing. Reworded to name the two endpoints explicitly and to make no claim about ledger appends in general.

Edit 2 — subject: whether `InspectionEncounter` carries/exposes a citation reference.
(b) Paths enumerated: `serial.encounter_out` (fixed field list, no `citation_id`), `routes_deployments.py:237-252` encounter record construction, `:257` `resolve_encounter` (mutates `outcome` only), `:299` `list_encounters` filters (`deployment_id`, `inspector_id`, `rider_id`, `outcome` — no citation filter, matching PRD §2.3), `cascade.void_deployment` (mutates `outcome` only), `routes_citations.py:103` duplicate-citation guard and `:32` `_mint_citation` (link stored as the citation's `encounter_id`), `routes_citations.py:135` citations-list `encounter_id` filter, `routes_reports.py` equity "cited" test (resolved citation->encounter), `core.base_record` (injects only `id`/`created_at`/`updated_at`/`version`/`_seq`).
(c) Adjustment: wording kept to "the encounter row records no reference back to the citation, and no citation identifier appears among the encounter's fields" — deliberately phrased about the encounter's own representation rather than asserting anything about how the reverse lookup is performed, so the equity report's citation->encounter join and the `encounter_id` filters remain accurately described.

Not patched (verified as pure test-side defects with no PRD implication): the `zone_code` fixture literals (PRD line 146 already pins 3-32 characters, and the impl enforces exactly that), the `test_17` balance arithmetic (PRD line 236's identity already matches `calc.refresh_citation_money`), and the `test_helpers/types.py` TypedDict cleanup (covered by Edit 2's subject, no separate behavior).

**Orchestrator verification:** `cmp` confirms PRD_FINALIZED.md is NOT byte-identical to PRD.md; both 454 lines, the two insertions landed inside existing paragraphs.

## Step 9: Complete PRD — 2026-09-04T12:25:00.000Z

Run as THREE sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (a single-shot full scan reliably under-scans a 3000-line implementation and can leave the output byte-identical to its source). Pass 1 owned the `cp`; passes 2 and 3 were forbidden from running it. **46 patches total: 36 ambiguity-pins, 10 mismatch-revisions. 454 -> 454 lines, +16,514 chars over PRD_FINALIZED.md.**

### Pass 1 — `core.py`, `calc.py`, `serial.py`, `cascade.py`, `app.py` (13 ambiguity-pins, 1 mismatch)
- §2.1 — revise — ambiguity — a header holding only whitespace counts as empty; role comparison is case-sensitive with no trimming — `core.py:316-319`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars; `api_request_timestamp` reads real wall-clock time, not the logical clock — `core.py:252-256`
- §2.3 ¶1 — revise — ambiguity — empty `limit`/`offset` fall back to defaults; non-integer or out-of-bounds -> `ERR_INVALID_REQUEST` 400; equal-`created_at` ties broken by creation order — `core.py:335-353,243-245`
- §2.3 ¶2 — revise — ambiguity — filter values matched literally and never enum-validated, so an undeclared value returns an empty page rather than an error — `core.py:495-502`
- §2.4 ¶1 — insert — ambiguity — every "empty" field is always present and serialized as JSON `null`, never omitted, never `""`, never 0 — `serial.py:13-18`
- §2.5 — insert — ambiguity — non-window instants that are unparseable/non-UTC -> `ERR_INVALID_REQUEST` 400, never `ERR_INVALID_TIME_WINDOW` — `core.py:457-482`, `routes_reports.py:150-155`
- §2.5 — insert — ambiguity — `Z` or `+00:00` both accepted; sub-millisecond precision retained for comparison but truncated (not rounded) to 3 digits on output — `core.py:112-145`
- §2.7 — insert — ambiguity — JSON-type split: `signage_compliance_pct` / `sample_adequacy_ratio` are JSON numbers (0.9000 -> `0.9`) while the equity report's four rates are decimal strings — `core.py:172-178`, `serial.py:29,121` vs `routes_reports.py:83-101`
- §2.10 — insert — ambiguity — four schema conventions: explicit `null` == omitted; booleans and fractional numbers fail integer fields; required strings reject `""`; absent/unparseable/non-object body -> `ERR_INVALID_REQUEST` — `core.py:369-425`
- §3.1 — revise — ambiguity — third-level audit tie (identical `audited_at` AND `created_at`) resolved by filing order — `calc.py:105-106`
- §3.3 — insert — ambiguity — the three deployment counters are also recomputed on every read, including after `CLOSED`/`VOIDED` — `serial.py:109`
- §3.3 — insert — ambiguity — `sample_adequacy_ratio` is NOT capped at 1.0000, unlike `signage_compliance_pct` — `calc.py:240` vs `109-110`
- §3.5 — revise — ambiguity — the money identity is also recomputed on every citation read — `serial.py:151`
- §3.8 — insert — ambiguity — `missed_installment_count` is the one plan counter not refreshed on read, while `installments_paid_count` and `remaining_balance_cents` are — `serial.py:214`, `calc.py:298-303`
- §5 preamble — revise — **mismatch** — `ERR_INVALID_REQUEST` is not 400-only; it is also returned at 404 (unrouted path), 405 (undeclared method) and 500 (unexpected fault), always inside the §2.2 error envelope — `app.py:38-53`

### Pass 2 — `routes_zones.py`, `routes_deployments.py` (9 ambiguity-pins, 2 mismatches)
- §2.6 — insert — ambiguity — `limit`/`offset` are screened BEFORE the parent path id is resolved on nested reads, so a malformed page window against a nonexistent parent reports `ERR_INVALID_REQUEST`, not the parent's 404 — `routes_zones.py:145-146`
- §3.1 ¶2 — insert — ambiguity — the `DRAFT` line-attachment gate accepts any assignment naming the zone; `effective_from` is not compared against anything — `routes_zones.py:67`
- §3.1 ¶3 — insert — ambiguity — `audited_at` is never compared to the logical clock, so a future-dated audit is accepted and becomes authoritative immediately — `routes_zones.py:156`
- §3.1 ¶4 — insert — ambiguity — filing an audit bumps zone `version` and `updated_at` unconditionally, even when non-authoritative, inert, and tripping no suspension — `routes_zones.py:177`
- §3.1 ¶8 — insert — ambiguity — revocation neither clears nor writes `suspension_reason`, and leaves `designated_at` as-is — `routes_zones.py:119-122`
- §3.2 ¶4 — insert — ambiguity — `GET /riders/{id}` is not owner-scoped; a `Rider` may read any rider record and `ERR_NOT_RESOURCE_OWNER` never arises — `routes_zones.py:327-331`
- §3.3 ¶1 — insert — ambiguity — absent/non-string `window_start`/`window_end` fail as `ERR_INVALID_REQUEST` at the schema step; only present-but-malformed/non-UTC reaches `ERR_INVALID_TIME_WINDOW` — `routes_deployments.py:37-38`
- §3.3 ¶5 — insert — ambiguity — activation guard order is from-state -> zone-designation -> clock, so a not-yet-begun window in a non-`DESIGNATED` zone reports `ERR_ZONE_NOT_DESIGNATED`; and there is no upper temporal bound, so a shift past `window_end` may still be activated — `routes_deployments.py:113-124`
- §3.3 ¶8 — revise — **mismatch** — PRD asserted `UNRESOLVED_IDENTITY` encounters "are always non-compliant"; the resolve guard admits that disposition on `identity_capture_method == REFUSED` alone, so a `VALID`-verdict encounter can hold it and enlarges the published pool without touching the numerator — `routes_deployments.py:282-285`
- §3.4 ¶1 — revise — **mismatch** — no guard couples `rider_id` to `identity_capture_method`, so `REFUSED`+`rider_id` and `GOVT_ID`+no-`rider_id` are both accepted as submitted — `routes_deployments.py:198-206`
- §3.4 ¶2 — insert — ambiguity — the "`media_reference` omitted when `fare_media_type` is `NONE`" rule is convention only; nothing enforces it and `media_reference` never feeds the verdict — `routes_deployments.py:201`, `calc.py:118-139`
- §3.4 ¶5 — insert — ambiguity — refreshing the parent deployment's counters is not a mutation: `version`/`updated_at` are untouched on encounter create and resolve — `routes_deployments.py:253`

### Pass 3 — `routes_citations.py`, `routes_appeals.py`, `routes_settlement.py`, `routes_reports.py` (14 ambiguity-pins, 7 mismatches)
- §2.10 — insert — **mismatch** — the state-order list put citation adjudication state before hearing/appeal state, but impl screens the path-addressed record first — `routes_citations.py:241-247`, `routes_appeals.py:129-136`
- §3.5 — insert — **mismatch** — the seven-guard narrative order contradicted impl (disposition support ahead of identity and warning-first); pinned the real chain — `routes_citations.py:68-106`
- §3.6 — insert — ambiguity — fresh hearing's `dismissal_reason_code`/`reduced_penalty_cents` are empty; contest returns 201 with the hearing, not the citation — `routes_citations.py:176-189`
- §3.6 — insert — ambiguity — decide and cancel both answer 200 with the hearing record — `routes_citations.py:295,313`
- §3.6 — revise — **mismatch** — PRD said the one-citation-per-encounter rule "does not block the reissue"; impl blocks on a live sibling citation with `ERR_ENCOUNTER_ALREADY_CITED`, ahead of the reason and window tests — `routes_citations.py:204-210`
- §3.6 — insert — ambiguity — reissue returns 201 with the NEW citation; the original is not mutated — `routes_citations.py:222-224`
- §3.7 — insert — ambiguity — a `WITHDRAWN` prior appeal does not trigger `ERR_APPEAL_ALREADY_OPEN` — `routes_appeals.py:48-51`
- §3.7 — insert — ambiguity — fresh appeal's `dismissal_reason_code` is empty — `routes_appeals.py:68`
- §3.7 — insert — ambiguity — all four appeal transitions answer 200 with the appeal, never the citation — `routes_appeals.py:89,117,162,178`
- §3.7 — insert — ambiguity — withdrawal leaves `decided_by_user_id` and `dismissal_reason_code` empty — `routes_appeals.py:175-177`
- §3.8 — revise — **mismatch** — "Every route requires the citation to be adjudicatively live" is false: installment payment and delinquency assessment never read `adjudication_status`, so installments keep paying while the citation is `CONTESTED` — `routes_settlement.py:163-164,191-192`
- §3.8 — revise — **mismatch** — PRD ordered nothing-outstanding before payment-amount; impl is the reverse, making `ERR_NOTHING_OUTSTANDING` unreachable there; also pinned that `amount_cents` carries no schema range — `routes_settlement.py:54-58`
- §3.8 — insert — ambiguity — flagged item (i), see verdict below — `routes_settlement.py:78,105`
- §3.8 — insert — ambiguity — the plan's own `version` increments on every accepted installment, not just the completing one — `routes_settlement.py:182`
- §3.8 — insert — ambiguity — a sub-threshold delinquency assessment bumps `version`/`updated_at` only when the recomputed missed count actually changed — `routes_settlement.py:205-206`
- §3.8 — revise — **mismatch** — PRD ordered nothing-outstanding before alternative-already-active; impl is the reverse — `routes_settlement.py:266-273`
- §3.8 — insert — **mismatch** — `hours` presence is the only schema check: absent/null -> `ERR_INVALID_REQUEST` 400, but a present string/float/boolean -> `ERR_INVALID_SERVICE_HOURS` 422, raised AFTER `ERR_SERVICE_NOT_ACTIVE` — `routes_settlement.py:294-303`
- §3.8 — insert — ambiguity — assignment and citation `version` both bump on every hours posting; returns 200 with the assignment — `routes_settlement.py:319-321`
- §3.9 — insert — ambiguity — flagged item (ii), see verdict below; plus `window_start`/`window_end` echoed verbatim as supplied rather than re-rendered — `routes_reports.py:29-30,36,94-95,109`
- §3.9 — insert — ambiguity — window bounds screened left to right, so two malformed bounds report `window_start`'s failure — `routes_reports.py:21-25`
- §4 — insert — ambiguity — no GET anywhere applies an ownership narrowing, so a `Rider` may read any citation, ledger, hearing, appeal, plan or assignment — `routes_citations.py:116,147`, `routes_appeals.py:183`, `routes_settlement.py:212`

### Cross-pass flagged-item verdicts
**(i) `installment_count`** surfaces as `ERR_INSTALLMENT_COUNT_OUT_OF_RANGE` (422), not a schema 400: `routes_settlement.py:78` uses bare `req_int` (presence + integer type only) and the route re-checks the range at line 105 — LATE, after OCC pinning, rider ownership, `adjudication_status`, `settlement_status` and `ERR_ALTERNATIVE_ALREADY_ACTIVE`, so an out-of-range count against a `SATISFIED` citation reports `ERR_SETTLEMENT_STATUS_INVALID`. This contradicted §2.10's blanket "numeric fields within their declared ranges -> `ERR_INVALID_REQUEST`" and is now pinned.
**(ii) `group_by` / `basis`** are both required via `core.query_enum`. Absent or empty -> `ERR_INVALID_REQUEST` 400; present but outside the two-member set -> `ERR_INVALID_REQUEST` 400, never `ERR_INVALID_TIME_WINDOW`. Both evaluate BEFORE `_window()`, so an unknown `group_by` beats a malformed `window_start`.

### Integrity
No pass ran `cp` except pass 1. Passes 2 and 3 each verified the earlier passes' distinctive marker strings still present before and after their own edits (pass 2: 15/15; pass 3: 7/7 sampled markers). Pass 3's final check: 454 lines, 122,385 bytes, 27 headings, 128 table rows, ends on the complete final error-table row `| ERR_NOTHING_OUTSTANDING | 422 |`.

**Orchestrator independent verification:** `PRD.md` 105,191 B / `PRD_FINALIZED.md` 105,871 B / `PRD_COMPLETED.md` 122,385 B, all 454 lines. `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md — the scan genuinely ran. 27 headings intact, tail ends at a real section boundary. Step 9 changed no code, so the 8-round green sweep (117/117 x8) recorded in Step 7 remains valid.

---

# PIPELINE COMPLETE — all 9 steps finished.
