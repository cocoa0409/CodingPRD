# Worklog — task_1108_student_health_center_operations

## Step 1: Create task directory — 2026-08-10T15:35:00.000Z

Task directory pre-assigned by pipeline runner: `tasks/task_1108_student_health_center_operations` with `workspace/` subdirectory already present. Step 1 auto-index scan skipped per instruction; treating Step 1 as done.

Scenario: 1108. Student Health Center Operations (campus student health center): appointment scheduling & same-day triage, immunization requirement enforcement & holds, insurance eligibility (student plan vs external) & billing, pharmacy & lab services, communicable disease reporting & campus outbreak response, sports-physical & travel-clinic services, after-hours coverage & hospital referral, health-fee funding model.

Difficulty parameter: "generate task hard than expert level!" — passed through to prd-bench-scaffold-generator at Step 2 only.

## Step 2: Generate scaffold — 2026-08-10T16:35:00.000Z

Scaffold generation complete. All three artifacts are written and lint-clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_1108_student_health_center_operations/SCAFFOLD.yaml` (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1108_student_health_center_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1108_student_health_center_operations/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts
- **Entities: 17** (Student, InsurancePolicy, ImmunizationRequirement, ImmunizationRecord, Provider, OnCallShift, Appointment, Encounter, Prescription, MedicationStock, LabOrder, DiseaseCase, OutbreakInvestigation, Invoice, Payment, Referral, HealthFeePool)
- **Endpoints: 60** (incl. `POST /shc/_clock/set_current_utc` with the mandatory `2026-05-01T00:00:00Z` default and a deterministic 5-step sweep)
- **Error codes: 57**, all referenced by at least one validation/transition/endpoint
- **State machines: 12** — InsurancePolicy, ImmunizationRecord, Appointment, Encounter, Prescription, LabOrder, DiseaseCase, OutbreakInvestigation, Invoice, Payment, Referral, HealthFeePool (non-linear: OutbreakInvestigation cycle ACTIVE→CONTAINED→ACTIVE, Prescription self-loop, Invoice cyclic overdue loop, Appointment branching)
- **Calculations: 8** — invoice_payer_split (provisional/final variants), invoice_line_subsidy_rounding (per-line-then-sum pinned), pool_subsidy_waterfall (snapshot evaluation order), outbreak_case_count (rolling-168h vs ISO-week variants), triage_daily_quota, compliance_posture_derivation, stock_reorder_flag, invoice_balance_and_status
- **Concurrency rules: 2** (both OCC: policy-create-supersede on `Student.version`, dose-entry on `ImmunizationRecord.version`)

## Difficulty-rule instance counts (19 total, all rules ≥2)
dual_variant_calc: 2 · combinatorial_formula: 3 (modes a, b, c) · non_linear_state_machine: 2 · transitive_cascade: 2 (depth-3 sweep cascade, depth-2 dispense cascade) · priority_pair_validation_conflict: 2 (state vs fiscal; safety vs temporal) · boundary_precision_check: 2 (stock units; case count) · cross_entity_state_dependency: 2 (Encounter→Student posture; Referral→OnCallShift) · resource_temporal_overlap: 2 (half-open appointments vs closed-interval + 12h rest buffer on-call) · compensating_invariant: 2 (stock units; invoice money)

## Corner design
39 real instances across entities/state_machines/calculations/validations/endpoints/rbac/cross_cutting_layers/consistency_model + **8 excluded_because stubs** (each citing a §1.8 instance that already exercises the corner). Every error code has at least one triggering instance across the two design files.

## Lint
`scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (60 endpoints, 17 entities, 19 §1.8 + 39 §1.9 instances, 600 calls scanned). Two authoring issues were fixed to get there: `$.data[0].x` JSONPath captures and bracketed `grounds` items needed quoting in YAML flow context — no design changes resulted.

## Design decisions (recorded in worklog.md)
Holds are stored computed fields on Student (not a separate entity) so the sweep cascade stays acyclic; at most one OPEN HealthFeePool exists at any time, making "the OPEN pool" an unambiguous selector with no id-based tie-break; PROVISIONAL invoices always mean patient-pays-all with adjudication deferred to issue; segregation of duties is enforced via X-User-ID comparison on the case confirm→report handoff.

## Step 3: Copy shared files — 2026-08-10T16:36:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1108_student_health_center_operations/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T16:50:00.000Z

PRD generation is complete. Summary:

## Report

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1108_student_health_center_operations/workspace/PRD.md` — **373 lines**, 26 headings.

**Section list:**
- §1 Introduction (3 paragraphs: domain context / logical clock / three shaping properties)
- §2 Global Specifications (9 subsections): 2.1 Roles & identity semantics, 2.2 Response envelope (verbatim fixed block), 2.3 Pagination, 2.4 Logical clock & deterministic 5-step sweep, 2.5 Common resource properties & derived consistency, 2.6 Monetary precision (integer cents, round half up), 2.7 Nested retrieval / left-to-right 404, 2.8 OCC (both rules, exact error ids + 412), 2.9 Validation ordering (10 steps with worked example)
- §3 Business Logic (9 subsections, patient-journey chronological): 3.1 Registration & posture derivation, 3.2 Insurance create/supersede/verify, 3.3 Immunization requirements/records/doses/exemptions, 3.4 Booking (slots, triage quota, compliance gates), 3.5 Check-in → encounter → close (fee-covered pool debit), 3.6 Pharmacy (prescribe/dispense/restock, reorder threshold), 3.7 Lab orders → disease cases → outbreak investigations (rolling 168h vs ISO week), 3.8 Billing (subsidy rounding, pool waterfall, two-variant payer split, payments/voids), 3.9 After-hours referrals & on-call rota
- §4 Endpoint table (4 columns, 58 endpoints), §5 Error catalogue (2 columns, 57 errors)

**Scaffold sections covered:** all of them — entities (16), state machines (14 machines, 51 transitions), concurrency rules (2), calculations (7), validations (10 priority tiers), response envelope, endpoints (58), errors (57), roles (7 + `Any` pseudo-role, identity semantics translated per role).

**Zero-silence audit (all PASS):**
- Contract 1: 88/88 required field names present verbatim in backticks (2 passes; first pass missed 7 names, repaired in place).
- Contract 2: 70 targeted rule spot-checks + 28 sibling-branch/contract checks + 37 transition-precondition error ids + 14 side-effect phrases — all expressed; every state (37), every enum value (62), every error id (57) present.
- Contract 3: 514 backticked tokens scanned inside §3 — zero path tokens, zero bare HTTP-method tokens, zero method+path combos.

**Scattering / information-hiding techniques:** booking inputs split across §3.4 (core) and §2.9 (ordering); compliance gates live in §3.1 (derivation) but fire in §3.4 (booking) and §3.5 (clearance); pool constants (12000 visit subsidy, 25000 outbreak debit) embedded in their firing contexts; pinned rounding order and the waterfall snapshot rule expressed with the scaffold's rejected-alternative rationale; relationships implied through actions ("supplying `student_id`", "under the parent `invoice_id`") with no FK declarations; composite `A → B` tokens avoided so each state stands alone.

**Design decisions** (also appended to `/home/ubuntu/github/CodingPRD/worklog.md`): clock+sweep promoted to §2.4 as a system-wide principle; validation ordering rendered as a numbered 10-step list with one cross-category example; §3 organized by patient journey rather than the anti-pattern 7-section template; 1-paragraph §4 preamble covering the 201/200 status-code rule and the clock's 200.

Orchestrator note: PRD endpoint table grep shows 60 rows (24 GET + 36 POST) matching scaffold's 60 `method:` entries — doc subagent's "58" narrative undercounted; actual table is complete. Reconciliation re-verified at Step 9.

## Step 5: Generate unit tests — 2026-08-10T17:05:00.000Z

Done. Full test infrastructure generated for `task_1108_student_health_center_operations`.

## Test counts

- **Queue A (Difficulty): 38 tests** — all 19 instances (9 rules) covered with exactly ≥2 tests each, every docstring ending with `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner): 41 tests** — all 39 non-stub instances covered with ≥1 test each, tagged `Design: Corner/<section>/<instance.name>` (the `booking_temporal_rule_matrix` instance is split into 3 isolated single-violation tests).
- **Total: 79 tests** across 11 files.

## Instances skipped

None. All 19 difficulty instances and all 39 non-stub corner instances passed the PRD-first two-condition filter. The 8 `excluded_because:` corner stubs were not translated (as required); all 8 of their `difficulty_instance` cross-references verified to resolve to real §1.8 instances.

One adjudication note: corner instance `posture_grace_window_provisional_hold`'s recipe asserted `active_hold_types contains IMMUNIZATION` under GRACE, which **contradicts** PRD §3.1 ("a grace-period student shows neither (a provisional hold contributes no entry to the set)"). I asserted the PRD-verbatim outcome (`active_hold_types == []`) instead — the scaffold claim, not the test, was weakened.

## Verification performed

1. **Citation grep** — every test docstring's quoted PRD citation was machine-checked: a contiguous ≥8-word substring of each quote survives a whitespace-normalized literal grep of `workspace/PRD.md`. 79/79 PASS (one fix applied: `test_student_create_missing_required_full_name` re-cited to a contiguous §3.1 sentence).
2. **Collection check** — `pytest --collect-only` with `PYTHONPATH=.` collects exactly **79 tests**, zero errors.
3. **Coverage audit** — script cross-walked both YAMLs against parsed docstring tags: every queue A instance ≥2 tests, every queue B non-stub ≥1, zero orphan tags, exactly one Design tag per test, tag is the docstring's final line.
4. **No-skip audit** — zero `pytest.mark.skip` / `skipif` / `xfail` / `pytest.skip(` anywhere.
5. **Leak audit** — no "scaffold"/table references in generated comments or docstrings; pyflakes clean on all non-barrel modules.

## File layout

```
test_helpers/
├── __init__.py       # barrel: framework generics + all PRD-specific helpers
├── types.py          # 17 entity TypedDicts (all carry id/created_at/updated_at/version), 19 status/role enums
├── api_client.py     # ApiClient(GenericApiClient): 47 methods, one per PRD §4 endpoint
├── api_errors.py     # ApiErrorId (57 errors) + HTTP map, registered via set_error_http_status_map
├── assertions.py     # per-entity assert_* + assert_timestamp_prefix + money-conservation invariant
├── factories.py      # payload factories, input fields only
├── constants.py      # TRIAGE_DAILY_QUOTA=4, VISIT_SUBSIDY_CENTS=12000, OUTBREAK_* (3/168h/25000), REPORT_WINDOW_HOURS=24, etc.
├── test_users.py     # TEST_USERS per role + make_student_headers (entity-backed) + per-role builders + ANONYMOUS_HEADERS
└── fixtures.py       # composite setups: set_clock, make_student/provider/pool/requirement/record/stock/policy/verified_policy,
                      # book_and_check_in, make_suspected_case, create_confirmed_case, setup_active_outbreak,
                      # setup_issued_invoice, setup_overdue_invoice_scenario, setup_registration_hold_student,
                      # setup_clearance_blocked_encounter (OCC version threading built into make_policy)

test_suite/
├── conftest.py                       # session api fixture + 7 role-header fixtures
├── test_01_students.py               # 6 corner: defaults, 404, dup ref, computed-field ignore, required field, enum
├── test_02_appointments_booking.py   # 8 corner + 4 difficulty (half-open adjacency ×2, hold-beats-slot ×2)
├── test_03_encounters.py             # 4 corner + 2 difficulty (clearance gate)
├── test_04_pharmacy.py               # 3 corner + 10 difficulty (self-loop, state-beats-fiscal, on_hand boundary, reorder cascade, conservation)
├── test_05_immunization.py           # 3 corner (dose error matrix, grace posture, record OCC)
├── test_06_insurance.py              # 4 corner (verify matrix, student OCC, reverse FK, role denial)
├── test_07_labs_and_disease_cases.py # 3 corner (lab chain matrix, case matrix, report window + SoD)
├── test_08_outbreaks.py              # 2 corner + 6 difficulty (rolling-vs-ISO week, 3rd-case boundary, contain/reopen cycle)
├── test_09_billing.py                # 3 corner + 12 difficulty (provisional/final split, min-max clipping, per-line rounding, waterfall, void conservation, overdue cascade)
├── test_10_referrals_oncall.py       # 1 corner + 4 difficulty (on-call coverage gate, closed-interval overlap, 12h rest)
└── test_11_platform.py               # 3 corner (missing auth 400, envelope + pagination defaults, duplicate config)
```

## Step 6: Generate implementation — 2026-08-10T17:06:00.000Z

Implementation complete. Summary:

## Routes — 60/60
Verified via Flask `url_map` diff against SCAFFOLD.yaml §1.5: all 60 (method, path) pairs registered, zero extras (Flask's built-in `/static` route disabled via `static_folder=None`).

Full list: POST `/shc/_clock/set_current_utc`; POST `/shc/students`, GET `/shc/students/{id}`, GET `/shc/students/{id}/insurance-policies`; POST `/shc/insurance-policies`, POST `/{id}/verify`; POST `/shc/immunization-requirements`; POST `/shc/immunization-records`, GET `/shc/immunization-records[/{id}]`, POST `/{id}/doses`, POST `/{id}/exempt`; POST `/shc/providers`, GET `/{id}`, GET `/{id}/on-call-shifts`; POST `/shc/on-call-shifts`; POST/GET `/shc/appointments[/{id}]`, POST `/{id}/check-in`, `/{id}/cancel`; GET `/shc/encounters[/{id}]`, POST `/{id}/close`, `/{id}/prescriptions`, `/{id}/lab-orders`, `/{id}/invoice`, `/{id}/referrals` (+GET for lab-orders/referrals); GET `/shc/prescriptions[/{id}]`, POST `/{id}/dispense`, `/{id}/cancel`; POST/GET `/shc/medication-stocks`, POST `/{id}/restock`; GET `/shc/lab-orders/{id}` + `/disease-cases`, POST `/collect`, `/result`, `/review`; GET `/shc/disease-cases[/{id}]`, POST `/confirm`, `/report`, `/resolve`; GET `/shc/outbreak-investigations`, POST `/contain`, `/reopen`, `/close`; GET `/shc/invoices[/{id}]`, POST `/issue`, `/payments` (+GET), POST `/shc/payments/{id}/void`; POST `/shc/referrals/{id}/accept`; POST/GET `/shc/health-fee-pools`.

## File layout (all under `.../workspace/implementation/`)
- `start.sh` (executable), `requirements.txt` (flask), `app.py` (entry, error handlers, blueprint registration)
- `store.py` (in-memory dicts, empty at boot; logical clock at 2026-05-01T00:00:00Z; `new_entity`/`bump` OCC helpers)
- `helpers.py` (envelope, ApiError, auth middleware, field validators, pagination)
- `services.py` (posture derivation, sweep, all calculations)
- `serializers.py`, `routes_a.py` (clock/students/policies/immunization/providers/shifts/appointments), `routes_b.py` (encounters/pharmacy/labs/cases/outbreaks), `routes_c.py` (billing/referrals/pools)

## State machines implemented
All 13: InsurancePolicy (verify/supersede/expire), ImmunizationRecord (PENDING→GRACE→OVERDUE sweep, direct PENDING→OVERDUE, dose→IN_COMPLIANCE, EXEMPTED), Appointment (BOOKED→CHECKED_IN/CANCELLED/NO_SHOW, cascade COMPLETED), Encounter (OPEN→CLOSED with 4-part gate), Prescription (WRITTEN→PARTIAL→DISPENSED, cancel), LabOrder (ORDERED→COLLECTED→RESULTED→REVIEWED), DiseaseCase (confirm/report/resolve with 24h window + SoD), OutbreakInvestigation (ACTIVE↔CONTAINED cyclic + auto-open/reopen), Invoice (DRAFT→ISSUED→PARTIALLY_PAID/OVERDUE→PAID + void re-derivation), Payment (POSTED→VOIDED), Referral (INITIATED→ACCEPTED), HealthFeePool (OPEN→CLOSED).

## Calculations implemented
Per-line round-half-up subsidy then sum (pinned order), pool waterfall with pre-invoice snapshot and single post-build debit, provisional vs adjudicated payer split (copay/deductible/coinsurance, Decimal ROUND_HALF_UP), rolling 168h outbreak count (threshold 3, inclusive bounds), triage daily quota (4, BOOKED/CHECKED_IN only), compliance posture derivation (IMMUNIZATION/FINANCIAL hold types), stock reorder flag (inclusive `<=`), invoice balance/status re-derivation with money conservation.

## start.sh contract verification
- Fresh boot: killed/relaunched repeatedly; store empty on every boot (verified `total_count: 0` and re-creating the same `external_ref` after reboot → 201)
- `$PORT`: honored (tested 19999/20001), defaults to 10000 when unset
- Binds `0.0.0.0` (verified via `ss -ltn`)
- Foreground: `exec python3 app.py`; pip install guarded by `import flask` check
- Storage: in-memory dicts only; no seeding anywhere (audited)

## Design decisions recorded in worklog
Logical clock drives all timestamps including `meta.api_request_timestamp`; `fee_covered` computed at check-in (enrollment immutable — no update endpoint exists); PRD §3.8 re-derivation wins over the scaffold's literal OVERDUE→PARTIALLY_PAID edge (partial payment on OVERDUE keeps OVERDUE); elective HOLD-cancellation only on record/invoice OVERDUE transitions, not void-induced ones; student version bumps only on actual posture/hold-type changes. 142 smoke assertions all green (isolation constraint respected — test_suite/test_helpers never touched).

## Step 7: Run tests and iterate — 2026-08-10T17:25:00.000Z

All 8 parallel rounds completed with 79/79 tests passing — a clean sweep on the first iteration.

## Summary

- **Iterations run:** 1
- **Tests deleted:** None
- **Fixes applied to `test_suite/`:** None
- **Fixes applied to `test_helpers/`:** None
- **Fixes applied to `implementation/`:** None

The 8-round parallel stability sweep at `/home/ubuntu/github/CodingPRD/tasks/task_1108_student_health_center_operations/run_sweep.sh` returned `passed=79 total=79 failed=0 error=None` on every round. No flakiness was observed, so no diagnostic protocol steps (PRD coverage check, test-vs-PRD consistency check, or implementation fix) were required. The task is already in a fully green, stable state.

Orchestrator verification (disk, not subagent claim): all 8 `results.{1..8}.json` present (~21KB each, non-identical bytes across rounds), each `total=79 passed=79 failed=0 errors=0 skipped=0` with 79 distinct per-test entries; per-round duration_seconds ≈ 131s (≈1.6s/test under per-test-server isolation), 8 concurrent rounds ≈ 2.6min wall — plausible and consistent. Route-vs-endpoint reconciliation before the sweep: 60/60 (method, path) pairs match SCAFFOLD.yaml §1.5 exactly, zero extras.

## Step 8: Finalize PRD — 2026-08-10T17:25:30.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced; Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-08-10T17:35:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1108_student_health_center_operations/workspace/PRD_COMPLETED.md` is written as a minimal patch over PRD.md.

**Stats**
- PRD.md: 373 lines / 56,166 chars → PRD_COMPLETED.md: 375 lines / 59,292 chars (char delta **+3,103**; diff touches 30 lines: 14 revised in place + 2 inserted lines, rest are context).
- Counts: **16 ambiguity-pins** (one covering 9 §4 table rows) and **5 mismatch-revisions**.

**Mismatch-revisions (PRD described different behavior than impl)**
- §2.7 — revise — mismatch — "before any body validation runs" softened to "before any business-rule body validation runs"; structural body validation (missing/mistyped/out-of-range fields → `ERR_INVALID_REQUEST`) pinned as running before existence checks — impl validates body shape first in every write endpoint (e.g. routes_c.py:46-62 before encounter lookup at :62; routes_a.py:101-117 before student lookup at :119).
- §3.1 — revise — mismatch — `enrollment_status` no longer "may later take LEAVE/WITHDRAWN"; pinned as registration-only, immutable, null→ENROLLED, invalid→`ERR_INVALID_REQUEST` — no update endpoint exists (routes_a.py:65-70; only POST /shc/students writes it).
- §3.2 — revise — mismatch — student `version` bump tied to every successful policy create, not only supersession — routes_a.py:151 `bump(student)` is unconditional.
- §3.5 — revise — mismatch — `fee_covered` decided at **check-in** (flag frozen at encounter creation, enrollment evaluated at that moment), not at close time — routes_a.py:525 computes it in `check_in`; routes_b.py:93,117 only read the stored flag.
- §3.9 — revise — mismatch — provider `active` flag no longer "governs whether the provider can take new appointments and shifts"; pinned as stored/returned only, never enforced — no reference to `active` in booking (routes_a.py:420-477) or shift creation (routes_a.py:368-405).

**Ambiguity-pins (PRD silent; pinned to impl)**
- §2.2 — insert — ambiguity — `meta.api_request_timestamp` read from the logical clock — helpers.py:74,84 (`fmt_dt(clock.now())`).
- §2.2 — insert — ambiguity — undefined path/unsupported method → `ERR_NOT_FOUND` 404; non-object JSON body → `ERR_INVALID_REQUEST` — app.py:28-40, helpers.py:108-114.
- §2.3 — insert — ambiguity — `limit`/`offset` out-of-range clamped, non-integers fall back to defaults — helpers.py:158-172.
- §2.3 — insert — ambiguity — sort ties broken by creation order; multiple filters combine conjunctively — helpers.py:177 (`(created_at, _seq)`), routes filter blocks.
- §2.4 — insert — ambiguity — clock setter accepts any timestamp (no monotonicity); responds `{"current_utc": ...}` — routes_a.py:45-52.
- §2.5 — insert — ambiguity — `created_at`/`updated_at` sourced from the logical clock — store.py:56-57, 70.
- §3.1 — insert — ambiguity — no-op posture recompute performs no write and does not bump student `version` (known decision) — services.py:73-76.
- §3.3 — insert — ambiguity — `min_interval_days`/`grace_period_days` ≥ 0, out-of-bounds → `ERR_INVALID_REQUEST` — routes_a.py:199-204.
- §3.3 — insert — ambiguity — record created already past deadline+grace also fires elective HOLD-cancellation at creation — routes_a.py:254-257.
- §3.4 — insert — ambiguity — list `date` filter matches the `scheduled_start` calendar date — routes_a.py:492-493.
- §3.6 — insert — ambiguity — `reorder_threshold` ≥ 0, negatives → `ERR_INVALID_REQUEST` — routes_b.py:221-224.
- §3.6 — insert — ambiguity — prescription create takes a positive `quantity` field (stored as `quantity_prescribed`), non-positive → `ERR_INVALID_QUANTITY` — routes_b.py:131,138-139.
- §3.8 — insert — ambiguity — invoice generation requires an `OPEN` encounter (`ERR_ENCOUNTER_NOT_OPEN`) and a non-empty well-formed `lines` list — routes_c.py:47-65.
- §3.8 — insert — ambiguity — DRAFT invoice's `balance_cents` initialized to `charge_total_cents` at generation — routes_c.py:85.
- §3.8 — insert — ambiguity — payment/void-induced re-derivation into OVERDUE recomputes posture but never fires elective HOLD-cancellation (known decision) — services.py:231-246 (no `cancel_future_electives` call, unlike `transition_invoice_overdue` at :99-103).
- §4 — revise — ambiguity — named the filter parameters on all nine list endpoints (immunization-records, appointments, encounters, prescriptions, medication-stocks, disease-cases, outbreak-investigations, invoices, health-fee-pools) — routes_a.py:262-274,480-496; routes_b.py:53-65,152-162,242-248,374-384,453-461; routes_c.py:95-105,266-272.

Other known decisions verified already-pinned in PRD (no change needed): partial payment on OVERDUE stays OVERDUE via due-date re-derivation (services.py:231-245 matches §3.8 prose); per-line round-half-up subsidy then sum and snapshot waterfall (services.py:163-190 matches §3.8); rolling 168h both-bounds-inclusive outbreak count excluding SUSPECTED/RESOLVED (services.py:253-261 matches §3.7). The §3.7 "ISO calendar-week metric" sentence was left untouched — it is explicitly non-normative ("never drives auto-open or auto-reopen") and has no endpoint-visible surface to contradict.
