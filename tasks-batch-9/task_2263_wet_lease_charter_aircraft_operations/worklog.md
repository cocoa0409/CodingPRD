# Worklog — task_2263_wet_lease_charter_aircraft_operations

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2263_wet_lease_charter_aircraft_operations/` and `tasks/task_2263_wet_lease_charter_aircraft_operations/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T00:00:00.000Z

All three artifacts are complete, parse cleanly, and pass the mechanical validator: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1424 calls scanned).

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2263_wet_lease_charter_aircraft_operations/SCAFFOLD.yaml` (3,443 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2263_wet_lease_charter_aircraft_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,574 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2263_wet_lease_charter_aircraft_operations/SCAFFOLD_CORNER_DESIGN.yaml` (5,749 lines)

## Counts
**SCAFFOLD.yaml** (§1.0–§1.7, contains neither design key): 13 entities, 12 state machines / 72 transitions, 2 concurrency rules, 8 calculations, 53 prioritised validations, 64 endpoints, 50 errors, 6 roles. `domain_name: wet-lease-charter-operations`, `api_prefix: /wetlease`. Roles: LessorOpsController, Lessee, RegulatoryAuthority, MaintenanceController, BillingAdmin, InsuranceUnderwriter. complexity_profile: primary `pricing_engine`, secondary `compliance_audit`, layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency, selector_policy]`, `role_model: segregation_of_duties`, `consistency_model: immediate`, `state_machine_shape: cyclic`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 23 instances covering all nine §0.5 rules — boundary_precision_check 4; combinatorial_formula, non_linear_state_machine, cross_entity_state_dependency 3 each; dual_variant_calc, transitive_cascade, priority_pair_validation_conflict, resource_temporal_overlap, compensating_invariant 2 each.

**SCAFFOLD_CORNER_DESIGN.yaml**: 81 instances = 63 with full `test_recipe` + 18 `excluded_because` stubs, across all nine §1.9 sections — entities 11, state_machines 20 (15 real), calculations 10 (6), validations 18 (14), endpoints 5, errors 5 (4), rbac 5, cross_cutting_complexity_layers 6 (2), consistency_model 1.

## Notable design decisions
- **Two independent pricing variants.** Every UtilizationPeriod carries a PROVISIONAL and a FINAL computation over the same legs; MGH proration, shortfall credit (payable only on lessor-attributable lost hours) and tiered overrun make the two diverge on identical inputs — the core `dual_variant_calc` pressure.
- **Cyclic state machines.** LeaseAgreement ACTIVE↔SUSPENDED (insurance lapse / AOG), CrewQualification QUALIFIED↔EXPIRED at an inclusive date boundary, and UtilizationPeriod PENDING_SETTLEMENT→DISPUTED→REOPENED→PENDING_SETTLEMENT (a reopened close deliberately does *not* spawn a following month), so no test can assume forward-only progress.
- **Deterministic substitute selector** with an explicit tie-break ladder (type family, seat floor, maintenance programme, hours-since-check ceiling), plus CLIENT_SPECIFIED override — this is the `selector_policy` layer and the source of the `ERR_NO_SUBSTITUTE_AIRCRAFT_AVAILABLE` path.
- **Priority-ladder conflicts are designed in, not incidental**: crew-duty safety outranks lease-term temporality on leg create; period-state outranks credit-limit on invoice prepare; type-rating (p50) outranks generic qualification (p54); discrepancies-open (p74) outranks invalid-state.
- **Segregation of duties** on the billing chain: the preparer of a SettlementInvoice cannot approve it, but may issue the approved one — enforced by `as_user_id` rather than role alone.
- **Closed-interval and exact-equality boundaries everywhere**: insurance minimum limits admit exact equality and reject one cent short; certificate coverage intervals are closed so touching endpoints collide; aircraft occupancy is half-open with a 45-minute buffer; credited hours round per leg then sum at four decimals.
- **Mandatory logical clock** (`POST /_clock/set_current_utc`, startup default `2026-08-01T00:00:00Z`, excluded from the Lessee role): every chain pins `2026-09-01T00:00:00Z`, with one state-machine chain advancing the clock mid-trigger to expire a checkride with no request against the row.
- All numeric literals in asserts were produced by executing `Decimal` arithmetic, and every corner instance was written only after querying the relevant endpoint's `input`/`output`/`roles`/`side_effects` and the entity field list out of SCAFFOLD.yaml.

Coverage audit is clean: zero unreferenced validations, zero unmentioned errors, zero unreferenced calculations, zero duplicate names across the two design files, zero unbound `${var}`, and all 18 stubs cite existing difficulty instances. The hard constraint was honoured throughout — no sibling `task_*/` directory (nor the stray `SCAFFOLD_CORNER_DESIGN.yaml` in the skill directory) was listed, globbed, grepped or read.

## Step 3: Copy shared files — 2026-09-01T00:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2263_wet_lease_charter_aircraft_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T00:00:00.000Z

All three Hard Contracts pass. PRD written to `workspace/PRD.md`.

**508 lines, ~13,100 words.** Domain: wet-lease / ACMI charter operations, mount `/wetlease`.

### Sections
- **§1 Introduction** — 3 paragraphs (the four-strand ACMI problem; what the API is the record of; the two design commitments: reproducible arithmetic, explicit cascades).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC, 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`, verified equal), 2.3 Pagination and List Ordering, 2.4 Resource Identity / Audit Fields / Logical Clock, 2.5 Money-Hours-Rounding Discipline, 2.6 OCC on Superseding Writes, 2.7 Cascade Discipline, 2.8 Validation Order (15-step ladder), 2.9 Conserved Quantities, 2.10 Two Independent State Dimensions on a Flight Leg, 2.11 Dual-Variant Evaluation.
- **§3 Business Logic** — 10 subsections grouped by lease lifecycle: onboarding parties; structuring the lease + regulatory filing/determination/revision loop; insurance cover; crew qualification and duty limits; activation/suspension/reactivation; flight legs; substitution and IROPS; monthly utilization + reliability; invoicing/SoD/disputes; termination and redelivery.
- **§4 Endpoint Definitions** — exactly 4 columns, all **64** endpoints.
- **§5 Error Code Catalogue** — exactly 2 columns, all **50** error IDs. Document ends at §5; no audit footer.

### Coverage audit (mechanically verified)
- **130/130** scaffold identifiers (entity fields + request-body fields + query params + path params) appear verbatim in backticks — 0 missing, checked twice.
- **50/50** error IDs appear in §2/§3 prose *and* in the §5 table; all 50 HTTP status codes match the scaffold.
- **64/64** endpoint method+path pairs present in §4; **6/6** roles named with identity translations (`Lessee` entity-backed; the other five opaque).
- **12/12** state machines: every `from`/`to` state token present. Both `concurrency_rules` (`expected_period_version`/`ERR_STALE_PERIOD_VERSION`, `expected_lease_version`/`ERR_STALE_LEASE_VERSION`, both 412) specified with rationale.
- **8/8** calculations with all **25** named constants expressed numerically; pinned rounding order (round-per-leg-then-sum, round-each-cents-component-then-sum, minutes floor down), strict-vs-inclusive boundaries, and the "penalty tier keyed on pre-penalty gross, no fixed-point iteration" rule all stated.
- Both 4-level cascades (insurance lapse; substitution effectuate) walked level by level; sibling-branch symmetry preserved for `LESSOR_UNILATERAL` vs `LESSEE_CONSENT_REQUIRED`, `PROVISIONAL` vs `FINAL`, `DEPARTURE` vs `SCHEDULED` basis, and the three suspension-recovery paths.
- **§3 path purity: 0 violations** — no backtick token in §3 starts with `/`, is a bare HTTP method, or combines method+path; §3 contains zero literal `/wetlease` or `/_clock` occurrences.
- No pseudocode: scan for `==`, `!=`, `>=`, `<=`, bare `IN`, `NULL`, `min(`/`max(`/`round(`/`floor(`, `+=`, `&&`, `||` and for fuzzy words ("approximately", "roughly", "conservatively") returned zero hits.
- Anti-pattern check: no §2/§3 heading reuses the example PRD's skeleton; top paragraph-starter bigram appears only twice across the document.

### Three scaffold internal conflicts resolved deterministically (flagging for the test-generation step)
1. `lifetime_credited_block_minutes` — the state machine has it accrue at period settlement (and reverse on FINAL-invoice void), while one endpoint's `side_effects` had it accrue at leg completion. The PRD adopts the settlement-driven rule and says explicitly that leg completion does not advance it.
2. Suspension cascades — the PRD cancels legs in `SCHEDULED` **or** `DISPATCHED` (stated in three endpoint side-effect blocks) rather than `SCHEDULED` only (stated once in the lease state machine).
3. Termination leg-cancellation scope — the PRD uses "every `SCHEDULED` leg whose `leg_class` is not `REPOSITIONING`" (state machine) rather than "`REVENUE` only" (endpoint), and spells out that this means `REVENUE` and `MAINTENANCE_FERRY`, sparing the redelivery ferry.

Also resolved a gap: `checkride_valid_until` exactly equal to the current logical date is specified to store the record as `EXPIRED` (the scaffold's `>` and `<` tests left equality undefined).

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, grepped, or referenced, and no sibling `task_*/` directory was read.

## Step 5: Generate unit tests — 2026-09-01T00:00:00.000Z

All nine translation passes are complete and the whole-suite audit is green.

## Files written

`test_helpers/` (Stage 1 infrastructure, 9 files): `__init__.py` (barrel), `types.py` (UserRole + 20 enums + 13 TypedDicts), `api_client.py` (`ApiClient(GenericApiClient)`, `PREFIX = "/wetlease"`, one method per endpoint, 64 endpoints), `api_errors.py` (`ApiErrorId` with all 50 ids + `HTTP_STATUS_CODES` + `set_error_http_status_map`), `constants.py` (all 8 calculation constant blocks + `TEST_DEFAULTS`), `factories.py` (one `**overrides` payload factory per write endpoint), `test_users.py` (`TEST_USERS` + `make_lessee_headers` / `make_billing_admin_headers` / four more builders), `assertions.py` (13 entity assertions + 4 domain-invariant checkers), `fixtures.py` (~600 lines of composite scenario builders).

`test_suite/` — `conftest.py` (thin bridge) plus 18 test modules:

| Queue B (Corner) | items | Queue A (Difficulty) | items |
|---|---|---|---|
| test_01_entity_records.py | 12 | test_10_settlement_variant_divergence.py | 4 |
| test_02_lease_lifecycle_transitions.py | 13 | test_11_charge_composition_arithmetic.py | 6 |
| test_03_operations_and_settlement_transitions.py | 12 | test_12_lease_and_leg_state_cycles.py | 6 |
| test_04_charge_and_selector_calculations.py | 10 | test_13_revocation_and_substitution_cascades.py | 6 |
| test_05_endpoint_behaviour.py | 11 | test_14_validation_precedence.py | 4 |
| test_06_validation_rules.py | 22 | test_15_threshold_boundaries.py | 8 |
| test_07_error_catalogue.py | 18 | test_16_cross_entity_gates.py | 6 |
| test_08_role_authorization.py | 14 | test_17_temporal_overlap.py | 4 |
| test_09_concurrency_and_visibility.py | 3 | test_18_conserved_quantities.py | 4 |

## Counts
- 142 test functions / **163 collected items**, `pytest test_suite --collect-only -q` → 0 errors.
- Queue A: 48 functions covering all **23** non-stub difficulty instances (>=2 each; the two `transitive_cascade` instances got 3).
- Queue B: 94 functions covering all **63** non-stub corner instances (>=1 each).
- **0 instances skipped.** Every non-stub instance in both indices survived the PRD-first filter.

## Audit results (all clean)
- Tags: 142/142 tests carry exactly one `Design:` line; no untagged, no dual-tagged, no tag resolving to a stub or to a non-existent name.
- Citations: every `PRD §x.y:` quotation is a byte-exact substring of `workspace/PRD.md` (0 misses across all 18 files).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no occurrence of "scaffold" or "design index" outside the tag lines.
- `pyflakes test_suite/*.py` clean; every `ApiErrorId.*`, `api.<method>` and bare helper call resolves statically. 49 of 50 catalogue error ids are exercised (only `ERR_RETURN_CONDITION_INVALID_STATE` is unexercised — no design instance targets it).
- All 18 corner `excluded_because:` stubs cross-reference a real difficulty instance and none was translated.

## Findings worth escalating (PRD won over the design literal in each case)
1. **Deposit at draft time** — three instances (`entities/lease_creation_returns_declared_fields_with_draft_status_and_zeroed_ledgers`, `state_machines/activation_without_any_insurance_certificate_...`) expect `return_deposit_remaining_cents == 0` before activation. PRD §3.2 and the §2.9 invariant both say a freshly drafted lease already carries `remaining == return_deposit_cents`. Tests assert the PRD.
2. **Checkride boundary** — `state_machines/checkride_validity_is_a_closed_boundary_...` labels the boundary inclusive; PRD §3.4 requires *strictly later* than the logical date, so an equal date is `EXPIRED`.
3. **Diverted leg billing state** — that section's weather instance expects `UNBILLED`; PRD §3.6 says `CREDITED`.
4. **Enum value names in recipes** — `cancel_reason: INSURANCE` (PRD: `INSURANCE_LAPSE`), `termination_reason: END_OF_TERM` (PRD declares `EXPIRY`/`NOTICE`/`DEFAULT`), `ERR_SEGREGATION_OF_DUTIES` as 409 (PRD/catalogue: 403).
5. **Non-observable projections** — several recipes assert *projected* rolling duty/block figures (3601, 4800) that the PRD only ever stores over the clock-anchored window; those single figures were dropped, the error-id outcomes kept.
6. **`version == 2` after close** — not asserted absolutely, because PRD §2.4 makes each provisional recomputation a mutation; asserted as `+1` relative instead.
7. **Corner-design defect (not fixed, reportable)** — stub `calculations/credited_hours_precision_covered_by_difficulty_instance` points at `boundary_precision_check / credited_hours_rounded_per_leg_then_summed`, but that instance lives under `combinatorial_formula`. The name resolves, so coverage is unaffected; only the rule_id prefix is wrong.
8. Two recipes carry unreachable setup steps (a trailing `activate` from `PENDING_REGULATORY_APPROVAL`, and a return-condition recipe omitting the crew qualification PRD §3.5 makes mandatory for activation); both were corrected to the PRD-legal chain.

## Step 6: Generate implementation — 2026-09-01T00:00:00.000Z

Implementation complete and verified.

## Files written

All under `workspace/implementation/` (24 files):

- `start.sh` — foreground launcher, `exec python3 app.py`, honours `PORT` (default 10000), binds `0.0.0.0`, guarded `pip install` (skipped when Flask already importable) so repeated per-test reboots don't contend.
- `app.py` — app factory, 11 blueprints, error handlers (`ApiError`, `HTTPException` with 404/405 → `ERR_INVALID_REQUEST`, bare `Exception` → `ERR_INTERNAL`).
- `db.py` — in-memory `Store` with 13 dicts, logical clock seeded to `2026-08-01T00:00:00Z`, row/version/`_seq` helpers, `public()` stripping `_`-prefixed internals. **No seeding of any entity data.**
- `errors.py` (50 PRD error IDs + `ERR_INTERNAL`), `response.py` (meta envelope, `req_` + 20-char id, pagination meta), `middleware.py` (RBAC, lessee ownership/scoping), `validate.py` (typed field validators).
- `services/calculations.py` (8 named calculations, `Decimal`/`ROUND_HALF_UP`), `services/workflows.py` (cascades, period lifecycle, conserved-quantity recomputation).
- `routes/`: `common.py`, `parties.py`, `leases.py`, `approvals.py`, `insurance.py`, `qualifications.py`, `legs.py`, `substitutions.py`, `billing.py`, `reliability.py`, `returns.py`, `clock.py`.
- `requirements.txt` (Flask 3.1.3).

## Endpoints

**64 registered routes**, matching the PRD §4 table one-for-one (verified by enumerating `app.url_map`), including `POST /_clock/set_current_utc`.

## Verification

`bash start.sh` boots clean from a fresh process; an end-to-end smoke script (lease → approval → insurance → activation → flying → period close → invoice prepare/approve/issue → dispute/REOPEN → substitution → termination → redelivery) reports `ALL SMOKE CHECKS PASSED`, with hand-checked arithmetic (mgh 2.0 h, credited 4.0833 h, tiers → 134123 + base 100000 = gross 234123, 2 % penalty 46825, final 187298) matching server output. Negative RBAC/pagination/404/401 cases pass.

## PRD-over-SCAFFOLD conflicts (PRD wins)

1. SCAFFOLD has leg `complete` increment `lifetime_credited_block_minutes`; PRD §2.9 says completing a leg does not advance it → only period settlement does.
2. SCAFFOLD says a new certificate doesn't auto-reactivate; PRD §3.3/§3.5 say an `INSURANCE_LAPSED` suspension lifts automatically → auto-reactivate on a conforming certificate.
3. SCAFFOLD lists `LessorOpsController` as actor for period OPEN→PENDING_SETTLEMENT; PRD §4/§3.8 say `BillingAdmin` → BillingAdmin.
4. SCAFFOLD lists `LessorOpsController` for return `inspect`; PRD §4 says `MaintenanceController` → MaintenanceController.
5. PRD §3.2 (revoke only `QUALIFIED`) vs §3.4 ("whether TRAINING, QUALIFIED or EXPIRED") → revoke-all.

## Ambiguities resolved with a concrete behaviour

- `created_at`/`updated_at` from wall-clock; the logical clock governs only expiry/window/coverage evaluation and `decided_at`. `_seq` breaks `created_at` sort ties.
- Input datetimes/dates echoed verbatim; parsed forms cached in stripped internal fields.
- `version` bumps on derived recomputation only when a value actually changes; explicit transitions always touch.
- Uncatalogued failures (certificate/qualification/report state guards, `conditions` payload rules, `actual_in > actual_out`, duplicate report month) → `ERR_INVALID_REQUEST` 400.
- Uniqueness enforced for `tail_number` and report `period_month` per (lease, aircraft) only; `icao_code`/`employee_no`/`certificate_no` deliberately not enforced (no error code exists, and fixture reuse would break unrelated flows).
- Lease-state allow-lists: certificate attach {DRAFT, PENDING_REGULATORY_APPROVAL, APPROVED, ACTIVE, SUSPENDED}; leg create {ACTIVE}; substitution {ACTIVE, SUSPENDED}; reliability report {ACTIVE, SUSPENDED, TERMINATING}.
- Lessee list reads scoped; single reads 403 on ownership mismatch; unassigned aircraft stay readable.
- First inspection with empty codes but non-zero computed cost → `DISCREPANCIES_OPEN`; deposit waterfall always recomputed from the full `return_deposit_cents`.
- Dispute `REOPEN` performs the full void reversal (legs back to `PROVISIONALLY_BILLED`/`UNBILLED`, lifetime minutes subtracted, receivable decremented) but lands the period in `REOPENED`, and a subsequent `close` returns it to `PENDING_SETTLEMENT` without opening a next month.
- Cascade cancellations set `billing_state = CREDITED` and `cancelling_party = LESSOR`.
- Two deliberate validation fall-throughs per PRD §2.8: substitution `effectuate` reaches `ERR_SUBSTITUTION_CONSENT_REQUIRED` after aircraft/programme checks, and return `close` lets `DISCREPANCIES_OPEN` past the state guard to reach `ERR_RETURN_DISCREPANCIES_OPEN`.

The forbidden paths (`test_helpers/`, `test_suite/`, the two `SCAFFOLD_*_DESIGN.yaml` files, sibling `task_*/` dirs) were never read, listed, globbed, or grepped.

## Step 7: Run tests and iterate — 2026-09-01T00:00:00.000Z

All 8 parallel rounds pass 163/163.

## Summary

**Iterations run:** 2 (sweep 1 → 1 failing test in all 8 rounds; sweep 2 → clean).

**Tests deleted:** none. No test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on the one failing path.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_validation_rules.py` — `TestReturnClosureGates::test_closure_admitted_once_the_repositioning_leg_has_flown`: rebuilt the setup so the repositioning ferry is dispatched and completed **while the lease is still `ACTIVE`**, and added a second, never-flown ferry to carry the `ERR_REPOSITIONING_LEG_INCOMPLETE` assertion. Also dropped the now-unused `dispatch_leg` import.

### Diagnosis detail for the single failure
The test failed identically in all 8 rounds of sweep 1 with `Setup step failed with HTTP 409: ERR_LEASE_INVALID_STATE`. Trace: the test used the module-local `_terminating_lease_with_repositioning_leg(api, fly=False)` fixture, which schedules a `REPOSITIONING` leg and *then* terminates the lease, after which the test called `dispatch_leg(...)` on that leg — i.e. it dispatched against a lease in `TERMINATING`.

- STEP 1a/1b: PRD §3.10 verbatim covers everything the test *asserts* (`ERR_REPOSITIONING_LEG_INCOMPLETE` for a non-`COMPLETED` ferry; closure storing `repositioning_leg_id`, record → `CLOSED`, lease → `RETURNED`, airframe released, qualifications `REVOKED`) and PRD §3.6 covers the `billable_block_minutes == 120` figure for a repositioning leg. Coverage and unique derivability hold, so the test stays.
- STEP 2: the *setup* was the defect. PRD §3.6 states verbatim for dispatch: "It re-runs the gates at the dispatch instant rather than trusting the ones passed at scheduling: the lease must be `ACTIVE`". So a PRD-faithful server must reject dispatch on a `TERMINATING` lease, and the implementation's `ERR_LEASE_INVALID_STATE` was correct. §3.10's "repositioning legs are deliberately spared so the ferry to the redelivery station can still be flown" is a rationale clause and does not override the explicit dispatch-time `ACTIVE` gate — so the ferry must be flown before termination is served.
- Fix preserved every PRD-covered assertion rather than dropping any: the flown ferry (dispatched/completed pre-termination, actuals `06:05Z`→`08:05Z`, 120 block minutes) drives the successful closure, while a second ferry scheduled `2026-09-21T06:00Z`→`08:00Z` survives termination in `SCHEDULED` (PRD §3.10 spares repositioning legs) and supplies the incomplete-ferry refusal. No implementation check was weakened and no assertion was relaxed.

Orchestrator verification: `results.{1..8}.json` all report `passed=163, total=163`.

## Step 8: Finalize PRD — 2026-09-01T00:00:00.000Z

Done. `PRD_FINALIZED.md` written.

**Line counts:** PRD.md 508 lines → PRD_FINALIZED.md 508 lines (0.0% delta; all three edits are inline within existing paragraphs, no lines added or removed).

**Changes**

- §3.6 (Dispatch) — revise — named the previously unnamed error code on the dispatch-time lease gate (`the lease must be ACTIVE, else ERR_LEASE_INVALID_STATE`), recorded that this gate is tested ahead of the leg's own `SCHEDULED` guard, and stated that no leg class (repositioning ferry included) is exempt while the lease sits in `SUSPENDED`, `TERMINATING` or a terminal status — `implementation/routes/legs.py:169-173`
- §3.10 (Termination) — revise — replaced the rationale "so the ferry to the redelivery station can still be flown" with what the implementation actually yields: a ferry flown *before* termination is the evidence of repositioning; a still-`SCHEDULED` ferry survives termination in `SCHEDULED` but can no longer be released for departure — `implementation/routes/leases.py:316-318` + `implementation/routes/legs.py:170`
- §3.8 (FINAL variant include-set) — revise — dropped the false impossibility claim ("legs in `SCHEDULED` or `DISPATCHED` cannot exist when the final variant runs") and replaced it with "contribute nothing", noting the two contexts where the final variant genuinely runs with such legs present (settlement preview of any period; termination-driven close that spares repositioning legs) — `implementation/services/calculations.py:222-227`, `implementation/routes/billing.py:52-53,77-79`, `implementation/routes/leases.py:320-322`

**Per-edit pre-edit search log**

Edit 1 — §3.6 Dispatch
- (a) Subject: the lease-state gate on leg dispatch and the error code emitted for a non-`ACTIVE` lease; secondarily the relative order of lease-state vs leg-state guards.
- (b) Paths enumerated: `routes/legs.py` dispatch (`lease["status"] != "ACTIVE"` → `ERR_LEASE_INVALID_STATE` at :171, before the leg `SCHEDULED` guard at :173), schedule (:86-87 same code), complete (:205-206 — leg state only, no lease check), cancel (:243-244 — leg state only); grep of `ERR_LEASE_INVALID_STATE`/`ERR_LEG_INVALID_STATE` across all of `implementation/` (insurance.py:39, returns.py:61, leases.py:196/249/306/310/349, substitutions.py:43/139, reliability.py:34) to confirm no dispatch-adjacent path uses a different code; `routes/leases.py` activate (:247-249) to confirm a `SUSPENDED`+`AIRFRAME_AOG` lease can return to `ACTIVE`.
- (c) Adjustment: first draft said "once a lease has left `ACTIVE` … no leg of it may be dispatched", which the AOG reactivation path (`leases.py:255-263` restoring `ACTIVE`) would have made a false permanence claim; re-scoped to "while a lease sits in `SUSPENDED`, `TERMINATING` or a terminal status". Also deliberately enumerated only post-`ACTIVE` statuses (a subset claim) rather than asserting the full non-`ACTIVE` set, and kept the sentence inside the Dispatch paragraph so it cannot be read onto completion or cancellation, neither of which checks the lease at all.

Edit 2 — §3.10 Termination
- (a) Subject: what happens to `REPOSITIONING` legs when termination is served, and whether a spared ferry remains flyable.
- (b) Paths enumerated: `routes/leases.py:305-318` (termination refuses while any leg is `DISPATCHED`; cancels only `SCHEDULED` non-`REPOSITIONING` legs); grep of `REPOSITIONING` across `implementation/` → `routes/legs.py:19`, `routes/leases.py:317`, `routes/returns.py:118-122` (closure fitness: same lease, `REPOSITIONING`, `COMPLETED`, `dest_icao == redelivery_icao`), `services/calculations.py:125` (repositioning bills `block_minutes` exactly); `services/workflows.py:264-285` `suspend_lease` / `insurance_lapse_cascade` (these cancel *all* live legs including repositioning — i.e. the sparing rule is termination-only); `routes/legs.py:170` (dispatch needs `ACTIVE`) and `routes/leases.py:236-263` (no route back to `ACTIVE` from `TERMINATING`).
- (c) Adjustment: confined the new clause to the termination paragraph so it cannot be read as sparing repositioning legs in the insurance-lapse / AOG / docket-revocation cascades, which do cancel them; avoided phrasing it as a precondition or gate (there is no "ferry must be flown first" check anywhere) and expressed it purely as a consequence of the dispatch-time `ACTIVE` gate.

Edit 3 — §3.8 FINAL variant
- (a) Subject: the FINAL-variant include-set's treatment of `SCHEDULED`/`DISPATCHED` legs, and the claim about when the FINAL variant can run.
- (b) Paths enumerated: `services/calculations.py:203-236` (FINAL branch counts only `COMPLETED` plus half of `CANCELLED_LESSEE`; everything else silently drops out, and `lessor_cancelled_minutes` accumulates independently of variant); `services/workflows.py:131-156,193-203` (`compute_period`/`apply_charge`/`close_period`); every FINAL callsite — `routes/billing.py:52-53` (settlement preview, runs FINAL on a period in *any* status, so live legs certainly can be present), `routes/billing.py:69-83` (close endpoint, which does enforce no `SCHEDULED`/`DISPATCHED` leg of the month and does so for both `OPEN` and `REOPENED` sources), `routes/leases.py:320-322` (termination close, which enforces no such check).
- (c) Adjustment: initially scoped the exception to the termination-driven close alone; widened it to also name the settlement preview after finding `billing.py:52-53` evaluates FINAL on `OPEN` periods, and phrased the close-endpoint precondition without naming a source status so it stays true for both `OPEN` and `REOPENED` closes. Also kept "contribute nothing" as the behavioural statement so the derivable arithmetic is unchanged from the original PRD.

## Step 9: Complete PRD — 2026-09-01T00:00:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Line/char comparison

| | `PRD_FINALIZED.md` (source) | `PRD_COMPLETED.md` |
|---|---|---|
| Lines | 508 | 508 (±0) |
| Chars | 99,610 | 112,765 (**+13,155**) |

No sections, headings, paragraphs or list items were added or removed — all 43 changed paragraphs are in-paragraph inserts/revisions. (`PRD_FINALIZED.md` was confirmed the later version: it differs from `PRD.md` in 3 paragraphs, all of which read as post-`PRD.md` tightenings.)

## Counts
- **ambiguity-pins (PRD silent):** 34
- **mismatch-revisions (PRD said something else):** 9

## Changes

- §2.1 Identity semantics — insert — ambiguity — lessee scoping is a *narrowing filter* on lists (200 OK with own rows) and a 403 only on single reads; a row whose owning lease can't be resolved is unowned and readable (an `Aircraft` with null `assigned_lease_id`); a `Lessee` reading its own row is checked against that row's `id` — `middleware.py:83,92`
- §2.3 ordering — insert — ambiguity — `created_at` ties resolve to insertion order; `total_count` is post-filter/post-narrowing and `has_more` is `offset + len(rows) < total_count` — `db.py:101`, `response.py:45`
- §2.3 filters — revise — mismatch — corrected the declared filter set (adds `period_id`, `status`, `variant`), pinned exact-string conjunctive matching, undeclared query params silently ignored, and only the lease list's `lessee_id` existence-checked (`ERR_LESSEE_NOT_FOUND`) — `routes/common.py:68`, `routes/leases.py:152`
- §2.4 audit fields — revise — mismatch — `updated_at`/`version` move only when a stored value actually changes; recomputations that reproduce existing figures are silent (open-period provisional, crew exposure, lessee receivable, deposit split); closing a month is the one unconditional bump — `db.py:84`, `services/workflows.py:138`
- §2.4 clock — insert — ambiguity — the instant is accepted unconditionally (may move backwards), the call answers 200 with an empty `data` object, effects apply at set-time only, and expiry is *strict* (`now > expires_at`, `today > checkride_valid_until`) — `routes/clock.py:28`, `services/workflows.py:334`
- §2.6 superseding writes — insert — ambiguity — the losing earlier invoice is left untouched in `PREPARED`, never voided — `routes/billing.py:184`
- §2.7 cascades — insert — ambiguity — suspension cascade level two is gated on the lease being `ACTIVE` (otherwise level one stands alone, no reason written, no legs cancelled); the AOG path excepted, since its leg cancellation keys on the airframe — `services/workflows.py:264`, `routes/parties.py:158`
- §3.1 lessee — revise — mismatch — `icao_code` is only *expected* unique; no uniqueness check is enforced and a repeat is accepted; cents fields are non-negative integers — `routes/parties.py:23`
- §3.1 airframe — insert — ambiguity — `tail_number` is 5–7 chars of any composition, compared case-sensitively; seat/cycle counts are integers — `routes/parties.py:83`
- §3.1 maintenance events — insert — ambiguity — `RETURN_TO_SERVICE` leaves `airframe_hours_total` untouched; an accepted event answers with the updated `Aircraft` — `routes/parties.py:139`
- §3.1 crew — revise — mismatch — `employee_no` uniqueness is expectation only, unenforced — `routes/parties.py:191`
- §3.2 filing — insert — ambiguity — refiling picks the most recently created `DENIED` docket; the call answers `201` with the `RegulatoryApproval` docket, not the lease — `routes/leases.py:186`
- §3.2 determination — insert — ambiguity — `expires_on` overwritten only when supplied; the `APPROVED`-with-conditions and empty-`CONDITIONAL` failures are `ERR_INVALID_REQUEST` (400) raised ahead of existence/state checks; `DENIED` leaves both condition arrays intact — `routes/approvals.py:40`
- §3.2 clear-conditions — insert — ambiguity — non-`CONDITIONAL` is `ERR_APPROVAL_INVALID_STATE`; leftover open codes are `ERR_INVALID_REQUEST` (400); unknown supplied codes ignored; historical `conditions` preserved — `routes/approvals.py:87`
- §3.2 withdrawal — insert — ambiguity — dockets are revoked without touching `decided_at` or writing a reason; *all* non-`REVOKED` qualifications are revoked; a non-`ASSIGNED` airframe keeps its posture but loses the assignment; `suspension_reason` cleared; answers with the lease — `routes/leases.py:339`, `services/workflows.py:288,296`
- §3.2 withdrawal (qualification set) — revise — mismatch — PRD said only `QUALIFIED` qualifications are revoked; impl revokes `TRAINING`, `QUALIFIED` and `EXPIRED` alike — `services/workflows.py:296`
- §3.3 attachment — revise — mismatch — `certificate_no` uniqueness is unenforced; plus the certifiable lease-state gate (`DRAFT`/`PENDING_REGULATORY_APPROVAL`/`APPROVED`/`ACTIVE`/`SUSPENDED`, else `ERR_LEASE_INVALID_STATE`) tested before the floors and the overlap check — `routes/insurance.py:19,37`
- §3.3 supersession — revise — mismatch — *every* other `ACTIVE` certificate is superseded (not only a non-overlapping one, which is merely the necessary consequence of the overlap gate), and only on an `INSURANCE_LAPSED`-suspended lease — `routes/insurance.py:70`
- §3.3 revocation — insert — ambiguity — revoking a non-`ACTIVE` certificate is `ERR_INVALID_REQUEST` (400); the lease's own status constrains nothing — `routes/insurance.py:112`
- §3.4 enrolment — insert — ambiguity — created with both date fields null; admissible whatever the lease status or crew role/standing, and duplicates are allowed — `routes/qualifications.py:19`
- §3.4 checkride — insert — ambiguity — wrong qualification state or non-`ACTIVE` crew is `ERR_INVALID_REQUEST` (400), qualification state tested first — `routes/qualifications.py:63`
- §3.5 activation — insert — ambiguity — the gate order (lessee → lease status → airframe posture → commander → determination → cover → programme) and that the missing commander reports `ERR_CREW_NOT_QUALIFIED_FOR_LESSEE_PROCEDURES` — `routes/leases.py:237`
- §3.5 reactivation — insert — ambiguity — reactivation runs a *bare* coverage test (no additional-insured/endorsement/floor re-check, no determination, commander or programme re-test); any other `suspension_reason` fails with `ERR_LEASE_INVALID_STATE` — `routes/leases.py:237`
- §3.6 scheduling — revise — mismatch — the ladder runs in §2.8 order (crew safety *before* term and occupancy), the lease must be exactly `ACTIVE`, and there is **no airframe-posture gate** at scheduling, only occupancy — `routes/legs.py:86,91,96,99`
- §3.6 dispatch — revise — mismatch — crew safety runs *ahead* of the cover test (PRD had insurance first), and the exposure projection is anchored on the leg's own `scheduled_out` excluding the leg itself — `routes/legs.py:181,185`
- §3.6 completion — insert — ambiguity — a non-strictly-later `actual_in` is `ERR_INVALID_REQUEST` (400), tested only after the `DISPATCHED` guard — `routes/legs.py:205`
- §3.6 cancellation — insert — ambiguity — the party mapping governs `DISPATCHED` legs too — `routes/legs.py:246`
- §3.6 diversion — insert — ambiguity — `DISPATCHED` + `WEATHER` diverts whichever party is named; `cancelling_party`/`cancel_reason` still recorded and `actual_out` retained — `routes/legs.py:246`, `services/workflows.py:249`
- §3.7 client-specified substitute — insert — ambiguity — the original may not be its own substitute (`ERR_SUBSTITUTION_TYPE_MISMATCH`), and the programme test precedes eligibility — `routes/substitutions.py:45`, `services/calculations.py:330`
- §3.7 consent — revise — mismatch — the note is written only when supplied (PRD said "both record the note"); a non-pending request is `ERR_SUBSTITUTION_INVALID_STATE` — `routes/substitutions.py:119`
- §3.7 effectuation — insert — ambiguity — fixed gate order lease state → substitution state → substitute posture (`ERR_AIRCRAFT_UNAVAILABLE`) → programme → `ERR_SUBSTITUTION_CONSENT_REQUIRED` last — `routes/substitutions.py:138`
- §3.7 `repointed_leg_count` — insert — ambiguity — counted before level three, so legs re-pointed then cancelled still count — `routes/substitutions.py:181`
- §3.8 period creation — insert — ambiguity — born with `variant_applied` `PROVISIONAL`, `dispute_reason` null, `disputed_amount_cents` 0, all charge fields already evaluated, and `version` 1 — `services/workflows.py:165,189`
- §3.8 rounding — revise — mismatch — `credited_block_minutes` is the minute sum *rounded half up* to whole minutes, not a plain sum (matters for the `FINAL` half-minute lessee-cancellation contribution) — `services/calculations.py:236`
- §3.8 close — revise — mismatch — admissible from `OPEN` **or** `REOPENED` with the source guard first, the `version` bump unconditional, and next-month creation additionally gated on no period already existing — `routes/billing.py:75`, `services/workflows.py:193`
- §3.8 reliability filing — insert — ambiguity — lease must be `ACTIVE`/`SUSPENDED`/`TERMINATING` (`ERR_LEASE_INVALID_STATE`); `review_note` null at creation; duplicate filing is `ERR_INVALID_REQUEST` (400); the airframe need only exist — `routes/reliability.py:33,36`
- §3.8 review — insert — ambiguity — `review_note` written only when supplied; a ruling on a non-`SUBMITTED` report is `ERR_INVALID_REQUEST` (400) — `routes/reliability.py:93,97`
- §3.9 `line_items` — insert — ambiguity — each row's `hours` driver (`mgh_effective_hours`, `lessor_attributable_shortfall_hours`, per-tier hours re-derived at preparation, 0 for the penalty) and that all `cents` are positive magnitudes including the credit — `routes/billing.py:139`
- §3.9 issue — insert — ambiguity — an optional `due_on` on issue overwrites the prepared date; settlement fires only while the period is still `PENDING_SETTLEMENT` — `routes/billing.py:264,283`
- §3.9 dispute resolution — insert — ambiguity — `REOPEN` stamps the literal `void_reason` `PERIOD_DISPUTE_REOPENED` and fully reverses the settlement, landing directly in `REOPENED` — `routes/billing.py:126`
- §3.10 termination — insert — ambiguity — `termination_reason` is validated but never persisted; a `DISPATCHED` leg refuses with `ERR_LEG_INVALID_STATE` after the lease guard; the termination-driven closes open no following month; the call answers `201` with the `ReturnCondition` — `routes/leases.py:297,304,320,336`
- §3.10 return record — insert — ambiguity — the three redelivery readings are null until inspected — `routes/leases.py:329`
- §3.10 inspection — insert — ambiguity — any other record status is `ERR_RETURN_CONDITION_INVALID_STATE`; the first-inspection lease gate (`ERR_LEASE_INVALID_STATE`) precedes the record-state gate; a re-inspection makes no lease-state demand — `routes/returns.py:58`
- §3.10 inspection outcome — revise — mismatch — a first inspection opens `DISCREPANCIES_OPEN` on codes **or** non-zero cost (PRD keyed it on codes alone), and a re-inspection still carrying codes stays open, keyed on codes alone — `routes/returns.py:76`
- §3.10 closure — insert — ambiguity — `repositioning_leg_id` resolves before `returnId` (`ERR_FLIGHT_LEG_NOT_FOUND` wins); closure answers with the return record and drives the lease to `RETURNED` only from `TERMINATING` — `routes/returns.py:104,128`

No implementation or test files were modified; `results.8.json` still shows 163/163 passing.

Orchestrator post-Step-9 verification: one further independent `prd-bench-local-run --isolation per-test-server` sweep after PRD_COMPLETED.md was written reports `passed=163, total=163`.
