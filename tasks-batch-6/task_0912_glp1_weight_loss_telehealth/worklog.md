# Worklog — task_0912_glp1_weight_loss_telehealth

Scenario (verbatim from user):

> 912. Weight-Loss / GLP-1 Telehealth Program: eligibility & BMI/lab screening, provider consult & prescription, pharmacy (compounded/branded) routing & prior-auth, subscription & titration schedule, side-effect & check-in, coaching/nutrition add-on, insurance vs cash, discontinuation

Difficulty parameter: top of the Expert band (§0.4) and beyond — maximum density on the nine §0.5 difficulty rules.

## Step 1: Create task directory — 2026-08-03T11:47:00.000Z

Created `tasks/task_0912_glp1_weight_loss_telehealth/` and `tasks/task_0912_glp1_weight_loss_telehealth/workspace/`. Index 0912 = max existing (0911) + 1.

## Step 3: Copy shared files — 2026-08-03T11:47:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0912_glp1_weight_loss_telehealth/workspace/INSTRUCTION.md` (done early, alongside Step 1; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-03T12:52:00.000Z

All three artifacts are complete and lint-clean.

### Files written
- `SCAFFOLD.yaml` (2623 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2692 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (2366 lines)

### Density
| Dimension | Count |
|---|---|
| Entities | **14** (Patient, Provider, Pharmacy, SupplyLot, EligibilityScreening, Consult, Prescription, TitrationStep, PriorAuthorization, PharmacyOrder, Subscription, BillingCycle, CheckIn, CoachingSession) |
| Endpoints | **60** (`api_prefix: /glp1`, flat topology) |
| Error codes | **30** |
| State machines | **10** |
| Calculations | **9** (5 dual-variant) |
| Validations | 29 rows, 13 priority bands |
| Concurrency rules (OCC) | 2 |
| Conservation invariants | 3 |
| §1.8 instances | 30 (9 rules) · §1.9 instances | 55 (37 with recipes, 18 `excluded_because` stubs) |

**Non-linear state machines (6 of 10):** Prescription (*parallel* — `clinical_status` × `fulfillment_status` advance independently), PriorAuthorization (*cyclic* — DENIED→APPEALED→DENIED, capped at 2 appeals), Subscription (*cyclic* — ACTIVE↔PAUSED), EligibilityScreening (*cyclic + branching* — DEFERRED re-screen loop, three-way submit outcome), TitrationStep (*branching fork* — DUE→{ADMINISTERED | HELD | REDUCED} with divergent side-effect sets, plus HELD→DUE re-arm), Consult (*cyclic* — NO_SHOW→SCHEDULED); PharmacyOrder and CheckIn are additionally branching with compensation.

**Dual-variant calculations (5, five different entity domains):** `eligibility_bmi_assessment` (frozen 30.0 vs live 26.6), `cycle_medication_charge` (CASH_PAY 36500 vs INSURANCE_ADJUDICATED 11500), `titration_readiness_interval` (INTERVAL_ONLY planning date vs TOLERABILITY_ADJUSTED 42-day gate), `coaching_entitlement_balance` (RESERVED_INCLUSIVE 2 vs COMPLETED_ONLY 3000¢), `side_effect_severity_index` (rolling 9 vs since-dose-change 0).

### §0.5 checklist
1. dual_variant_calc — **5**
2. combinatorial_formula — **3** (mode a nested min/max/min; mode b round-per-component-then-sum 25934 vs 25933; mode c dispensing-fee waiver keyed on the subtotal excluding itself, 36500 vs 34000)
3. non_linear_state_machine — **3** instances (parallel / cyclic / branching, three entities)
4. transitive_cascade — **3** (depth-5 triage chain CheckIn→Prescription→TitrationStep→PharmacyOrder→SupplyLot; depth-3 cancel chain; depth-3 PA-denial chain)
5. priority_pair_validation_conflict — **3** distinct pairs (state/constraint, temporal/fiscal, referential/temporal)
6. boundary_precision_check — **4** (BMI exactly 27.0; interval 27 vs 28 days; score exactly 7; zero available units)
7. cross_entity_state_dependency — **3** entity pairs (Prescription↔Screening, PharmacyOrder↔PriorAuthorization, TitrationStep↔CheckIn)
8. resource_temporal_overlap — **3** distinct interval semantics (Provider 15-min two-sided buffer; Coach zero-buffer half-open adjacency; SupplyLot windowed *aggregate* capacity)
9. compensating_invariant — **3** conserved quantities (lot units, coaching credits, collected cash)

### Verification
- All three files pass `yaml.safe_load` (confirmed individually).
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (60 endpoints, 14 entities, 30 + 37 instances, 807 calls scanned).
- Zero unbound `${var}` placeholders across both design files; every OCC version input is a `${var}`.
- All 30 error codes are referenced by at least one design instance; no forbidden concurrency vocabulary anywhere.
- Every named constant has a concrete value: 14 in a new top-level `policy_constants:` block (buffers, caps, clock default `2026-05-01T00:00:00Z`) plus 35 in `calculations[].constants`. The only remaining ALL_CAPS tokens are enum members, state names, and calculation variant names.
- All formula-derived assertions were computed in Python before being written as literals (e.g. 36500 / 38900 / 11500 / 71000 / 33500 / 25934 / 35900, BMI 30.0 / 27.0 / 26.6 / 32.9 / 31.1 / 32.2).

**Orchestrator verification (independent):** all 3 files `yaml.safe_load` OK; entities=14, endpoints=60, errors=30, state_machines=10, calculations=9; 46 declared constants; ALL_CAPS sweep found 0 undeclared numeric constants (17 residual tokens are all enum members / reason codes).

## Step 4: Generate PRD — 2026-08-03T13:05:00.000Z

PRD generated at `workspace/PRD.md`.

**Line count:** 473. Ends at §5 with no audit footer. Written in 5 bounded Write/Edit calls.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Actors, Identity and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Retrieval · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Left-to-Right Path Resolution and Not-Found Routing · 2.7 The Order in Which a Request Is Screened · 2.8 Optimistic Concurrency · 2.9 Money, Counts and Rounding · 2.10 Conservation Guarantees · 2.11 Status Codes
- §3 Business Logic — 3.1 Enrolment, Directory and Physical Stock · 3.2 Eligibility Screening and Re-Screen Cycle · 3.3 Consult Booking/Closing/Rescheduling · 3.4 Prescription and Its Two Axes · 3.5 The Titration Ladder · 3.6 Payer Coverage and Cash Fallback · 3.7 Fulfilment: Routing/Reserve/Ship/Cancel · 3.8 Check-Ins, Triage, Hold Cascade · 3.9 Subscription Billing · 3.10 Coaching Entitlement Pool
- §4 Endpoint Definitions (4 columns, 60 rows) · §5 Error Code Catalogue (2 columns, 30 rows)

### Coverage audit

```
Field coverage check:
- entities[].fields:        114 unique required, 114 present, 0 missing
- endpoints[].input/query:   66 required,  66 present, 0 missing
- endpoints[].path_params:   12 required,  12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority:  29 checked, 29 expressed (full 13-rung ladder in §2.7;
                                same-rung ties pinned per operation in §3), 0 missing
- concurrency_rules[] OCC:       2 checked, 2 expressed (POST /glp1/prescriptions +
                                expected_patient_version + ERR_STALE_PATIENT_VERSION 412;
                                POST /glp1/pharmacy-orders + expected_prescription_version +
                                ERR_STALE_PRESCRIPTION_VERSION 412), 0 missing
- state_machines[].transitions: 48 checked across 10 machines, 48 fully expressed
                                (102 side-effect bullets, incl. every failure/compressed
                                branch: DEFERRED→DEFERRED restale, INELIGIBLE band=NONE,
                                CREATED→CANCELLED zero-counter path, PAUSED→CANCELLED
                                no-cascade path, OPEN→VOIDED zero-proration path,
                                score 7–8 escalate-without-hold branch), 0 missing
- calculations[]:                9 checked, 9 fully expressed (formula + pinned evaluation
                                order + rounding order + every constant's numeric value),
                                0 missing
- validations[] conditions:     29 checked, all matchable to their error_id in §2/§3 prose
- endpoints[].side_effects:     35 endpoints with side effects, all expressed; applies_to
                                sets enumerated verbatim (5 endpoints for
                                ERR_PRESCRIPTION_NOT_ACTIVE, 4 for ERR_SUBSCRIPTION_NOT_ACTIVE,
                                6 for the ownership rule, 9 for body-FK existence)
- entities[].fields structured: 141 field entries, all types/defaults/initial values placed
                                on the owning entity
- sibling-branch symmetry:      equal density on all fork groups (escalate|hold|reduce,
                                triage clear|escalate, cancel from CREATED|RESERVED,
                                void from OPEN|INVOICED|SETTLED, pause|cancel cascades,
                                cash|insurance pricing readings, both BMI variants,
                                both severity-index variants, both entitlement variants)
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 806
- tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path tokens: 0
Status: PASS
```

**Also verified:** all 60 endpoint paths appear in the §4 table; all 30 error IDs appear in §5 *and* at least once in §2/§3 narrative; all 14 policy constants and all 36 calculation constants (including both 5×2 dose-ladder tables and the 5-entry dose multiplier) have their concrete numeric values in prose; all 3 conservation invariants (INV-1/2/3) are stated as named identities with forward and compensating legs in §2.10.

**Nothing was left uncovered.** Three judgement calls worth flagging, where the scaffold pins a precondition but nominates no error code — routed each to the closest declared code rather than inventing one: reducing below `dose_level` 1, invoicing before `period_start_at`, and deciding a prior authorisation on a `DISCONTINUED` prescription all → `ERR_INVALID_STATE` (409); insufficient `available_units` at reserve → `ERR_LOT_CAPACITY_EXCEEDED` (409). Did not open either design yaml, nor any sibling task.

## Step 5: Generate unit tests — 2026-08-03T13:40:00.000Z

Test infrastructure and suite are generated and fully audited.

**Total: 100 tests** across 11 files, plus 9 helper modules.

### Per-queue coverage — complete, nothing skipped

- **Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`)**: all **30/30** instances translated, each with exactly **2 tests** (60 tests). No instance skipped.
- **Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`)**: all **37/37** non-stub instances translated (40 tests — three instances carry a second test where the recipe's assert list splits cleanly). The **18 `excluded_because` stubs were not translated**; all 18 `difficulty_instance` cross-references were checked and resolve to real queue-A instances.

Two instances needed a redesigned (not weakened) setup to survive the two-reader test, because the recipe as written left the error ambiguous between two PRD-consistent readings:

- `Difficulty/cross_entity_state_dependency/prescription_creation_requires_eligible_screening` — the recipe closes the consult `DECLINE`, so `ERR_INVALID_STATE` (§2.7 rung 8) and `ERR_SCREENING_NOT_ELIGIBLE` (rung 9) both fire. Split into one test asserting the below-band adjudication verbatim from the recipe, and one that isolates the screening gate (consult correctly `COMPLETED_PRESCRIBED` off an earlier eligible screening, prescription cites a later `INELIGIBLE` one) so only `ERR_SCREENING_NOT_ELIGIBLE` can fire.
- `Corner/state_machines/discontinued_prescription_is_terminal_and_locks_refill` — refill on an `UNROUTED`+`DISCONTINUED` prescription trips both the axis check and the clinical check at rung 8. Split into the recipe-faithful discontinue side-effect test plus a refill test where the order is shipped first, so `ERR_PRESCRIPTION_NOT_ACTIVE` is the only reachable outcome.

### File layout

```
test_helpers/   __init__.py  types.py  api_client.py (60 endpoint methods)
                api_errors.py (30 codes + status map)  assertions.py
                (per-entity + INV-1/2/3 checkers + instant comparison)
                factories.py  constants.py  test_users.py  fixtures.py (5 tiers)
test_suite/     conftest.py
                test_01_enrolment_and_directory.py       (11)
                test_02_eligibility_screening.py          (7)
                test_03_consult_calendar.py               (6)
                test_04_prescription_issue.py             (8)
                test_05_titration_ladder.py              (10)
                test_06_payer_coverage.py                 (6)
                test_07_fulfilment.py                    (12)
                test_08_side_effect_surveillance.py      (11)
                test_09_cycle_pricing.py                  (8)
                test_10_subscription_lifecycle.py        (10)
                test_11_coaching_entitlement.py          (11)
```

### Verification results (all green)

- `python3 -m py_compile` on all 21 files — OK
- `import test_helpers` — clean (230 exported names)
- `pytest --collect-only` — **100 tests collected, 0 errors**
- `pyflakes` on all test-suite and helper modules (excluding the intentional barrel re-exports in `__init__.py`) — **0 warnings**
- Design tags: every test carries **exactly one** `Design:` line; all resolve to real non-stub instances; no dual-tagged or untagged tests
- PRD citations: every quoted span in every docstring survives a whitespace-normalised literal match against `PRD.md`, and every test carries at least one verbatim quote of ≥8 words plus a `PRD §x.y` reference
- No `skip` / `skipif` / `xfail` / `pytest.skip(` anywhere
- No scaffold vocabulary (`scaffold`, `test_recipe`, `Table N`, `§1.x`) in any generated file

### Design notes worth carrying forward

- Timestamps are compared **semantically** (`assert_same_instant` parses both sides) rather than by string, avoiding the recurring `.000Z`-vs-`Z` rendering mismatch.
- Ownership is threaded correctly everywhere: `make_patient_headers(patient["id"])`, `make_provider_headers(...)`, `make_coach_headers(...)`, `make_pharmacy_operator_headers(order["pharmacy_id"])`. Shared `TEST_USERS` constants are used only for the opaque `BillingAdmin`/`PlatformAdmin` roles and for auth-probe tests.
- `fixtures.py` provides the ~9-call preamble as tiers: `setup_eligible_member` → `setup_prescribing_consult` → `setup_active_prescription` → `setup_prescription_with_stock` → `setup_routed_order`/`setup_reserved_order`/`setup_shipped_order`, plus `setup_subscription`/`setup_coaching_subscription`/`setup_invoiced_cycle`.

## Step 6: Generate implementation — 2026-08-03T13:40:00.000Z

Implementation complete and verified.

### File layout (line counts)

| File | Lines | Role |
|---|---|---|
| `app.py` | 100 | Flask app, blueprint registration, error handlers, request-serializing WSGI middleware |
| `store.py` | 195 | In-memory collections, logical clock, ISO parsing/rendering, per-request `touch()` |
| `errors.py` | 123 | 30 error ids + HTTP status map + `ApiError` |
| `envelope.py` | 51 | `meta`/`response_type`/`data` success, array and error envelopes |
| `auth.py` | 37 | `X-User-ID`/`X-User-Role` auth, role authorisation, ownership |
| `validation.py` | 226 | Body-shape + query validators, pagination, filters |
| `calculations.py` | 236 | All 9 calculations, all policy constants, `Decimal`/`ROUND_HALF_UP` |
| `services.py` | 388 | Lookups with 404 routing, cascades, routing selector, cycle/credit machinery |
| `serializers.py` | 93 | Per-entity field projections |
| `routes/directory.py` | 191 | clock, patients, providers, pharmacies, supply-lots (9 endpoints) |
| `routes/clinical.py` | 237 | screenings, consults (9) |
| `routes/prescriptions.py` | 293 | prescriptions, titration-steps (10) |
| `routes/payer.py` | 124 | prior-authorizations (5) |
| `routes/fulfillment.py` | 190 | pharmacy-orders (6) |
| `routes/billing.py` | 233 | subscriptions, billing-cycles (11) |
| `routes/surveillance.py` | 234 | check-ins, coaching-sessions (10) |
| `start.sh` / `requirements.txt` | 12 / 1 | launcher, deps |

~2,950 lines total.

### Endpoint-coverage gate

Programmatic diff of SCAFFOLD `endpoints[]` against a booted `app.url_map`:
```
scaffold endpoint count : 60 (unique 60)
registered route count  : 60 (unique 60)
MISSING: 0    EXTRA: 0    DIFF EMPTY: True
```
(No Step-6 partial-write gap.)

### Contract confirmations

- **start.sh**: reads `$PORT` (default 10000), `exec python3 app.py` binds `0.0.0.0`, foreground, `pip install` guarded on `python3 -c "import flask"`. Cold `bash start.sh` → first HTTP response in **451 ms**.
- **No seeded data**: storage is plain module-level dicts in `store.py`; nothing writes to disk. Verified live: a fresh boot returns `total_count: 0` on all 12 list collections and `current_utc: 2026-05-01T00:00:00Z`.

### Behavioural verification

Three end-to-end suites (~200 assertions) against live servers: auth/RBAC/ownership, all six 404 families, screening ladder incl. the DEFERRED re-screen loop and renal-before-BMI precedence, 15-min buffered consult overlap vs. zero-buffer coaching overlap, both OCC rules, supersession, discontinue cascade, full 5-rung ladder with second-signer segregation, PA approve/deny/appeal 3-hop cascade, FEFO routing with all seven candidate predicates, windowed lot capacity, INV-1/INV-2/INV-3 conservation, both pricing forks, 6-step invoice waterfall, per-component proration, settle credit-back asymmetry, pause/resume/cancel cascades, and the 9-score hold cascade with PROVIDER_HOLD survival. All pass.

### PRD ambiguities and the interpretation chosen

1. **§2.4 vs §2.5 — timestamp rendering.** §2.5 pins `created_at`/`updated_at` at three fractional digits; §2.4 says the clock "reads exactly `2026-05-01T00:00:00Z`". Chosen: **every server-written timestamp** (`created_at`, `updated_at`, `submitted_at`, `triaged_at`, `resolved_at`, `decided_at`, `reserved_at`, `shipped_at`, `invoiced_at`, `completed_at`, `administered_at`, `paused_at`, `last_dose_change_at`, `approved_through_at`, `earliest_escalation_at`, `api_request_timestamp`) renders `.mmmZ`; **caller-supplied datetimes are echoed verbatim** (never normalised in either direction); `period_end_at` is derived from `period_start_at` **preserving the source string's style**, so an anchor given plain-`Z` yields a plain-`Z` end and cycle *n+1*'s `period_start_at` is byte-identical to cycle *n*'s `period_end_at`. `current_utc` echoes the exact string last set.
2. **§2.7 rung 5 — enum routing.** No `ERR_INVALID_ENUM` exists in this catalogue; §2.7 and §5 both put "undeclared enum member" on `ERR_VALIDATION`. **Every** enum-membership field is routed to `ERR_VALIDATION` (400) — `payment_mode`, `provider_type`, `dispense_type`, lot/provider `status`, `drug_family`, `outcome`, `decision`, `discontinue_reason`, `comorbidity_codes` entries, and `void_reason ≠ ADMIN_REVERSAL`.
3. **§3.4 order of consult-state vs screening gate.** Prose lists the screening first, but the §2.7 ladder puts `ERR_INVALID_STATE` at rung 8 and screening eligibility at rung 9. Ladder wins: consult state first.
4. **§3.5 vs §3.8 — `severity_index_since_dose_change` after escalate.** §3.5 says it "necessarily resets to zero"; §3.8 defines the pool as `submitted_at` **at or after** `last_dose_change_at`. Implemented the §3.8 formula uniformly (which yields 0 in every case except a check-in submitted at the exact escalation instant).
5. **§2.5 — repeated mutation of one row in one request.** "increments by 1 on every mutation" is applied as **one bump per row per request** (a request-scoped touched set), so a pause that voids a cycle and forfeits three sessions bumps the subscription once, not five times.
6. **§3.5 hold/reduce with a `DISCONTINUED` prescription.** These two operations are not among the five `ERR_PRESCRIPTION_NOT_ACTIVE`-guarded ops (§2.7), so the "ACTIVE or HELD" requirement failing yields `ERR_INVALID_STATE` (409).
7. **§3.4 request-refill ordering.** Fulfilment-axis check first (`ERR_INVALID_STATE`), then clinical (`ERR_PRESCRIPTION_NOT_ACTIVE`), matching the scaffold's precondition order.
8. **§2.6/§2.7 — `second_signer_provider_id` existence.** Rung 6 covers only the nine creation ops, so an unresolvable second signer is checked inside escalate gate 4, ahead of the `ERR_SECOND_SIGNER_CONFLICT` tests, yielding `ERR_PROVIDER_NOT_FOUND` (404).
9. **§3.7 — fulfilment rewind during multi-order cascades.** The rewind to `UNROUTED` fires only on the `RESERVED → CANCELLED` path and only if no order remains `CREATED`/`RESERVED` **at that moment**; a still-`CREATED` sibling cancelled later in the same cascade therefore leaves the axis at `ROUTED` (literal reading, confirmed by test).
10. **`created_at` ties.** The logical clock is static, so list ordering and the routing selector's final tie-break fall back to insertion order via an internal sequence number — the lot `id` is never consulted, per §3.7.

## Step 7: Run tests and iterate — 2026-08-03T13:52:00.000Z

No orphan Flask servers. The sweep completed cleanly on the first iteration.

**Iterations run: 1** — the first full 8-round sweep came back clean, so no fix/rerun cycles were needed.

**Tests deleted: none.** No test failed in any round, so no test ever entered the STEP 1 coverage / unique-derivability triage.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/`: none.**

### Final counts

| Round | Passed / Total | Failed | Errors | Skipped | Wall |
|---|---|---|---|---|---|
| 1 | 100 / 100 | 0 | 0 | 0 | 65.9s |
| 2 | 100 / 100 | 0 | 0 | 0 | 63.1s |
| 3 | 100 / 100 | 0 | 0 | 0 | 64.5s |
| 4 | 100 / 100 | 0 | 0 | 0 | 64.3s |
| 5 | 100 / 100 | 0 | 0 | 0 | 60.2s |
| 6 | 100 / 100 | 0 | 0 | 0 | 58.9s |
| 7 | 100 / 100 | 0 | 0 | 0 | 58.9s |
| 8 | 100 / 100 | 0 | 0 | 0 | 58.5s |

Union of failing tests across all 8 rounds: **empty**. No flakiness surfaced.

### Verification performed before declaring the clean pass

Because a zero-fix result is exactly what a false-clean looks like, the printed `sweep.sh` summary was not accepted at face value:

- **All 8 `results.N.json` present and parseable** — each contains 100 individual test rows (not just an aggregate counter), all with status `passed`. No round died or wrote a partial file.
- **Identical test-name sets across all 8 rounds** — 100 unique names, zero set-difference between any pair of rounds, so no round silently collected a smaller suite.
- **Suite integrity** — 100 `def test_` functions across the 11 files, matching the runner's `collected 100 items` exactly; grep for `pytest.mark.skip` / `xfail` / `skipif` / `pytest.skip(` across `test_suite/` and `test_helpers/` returns nothing.
- **Storage purity (cardinal rule)** — grep for `sqlite`, `open(`, `json.dump`, `pickle`, `shelve`, `/tmp` across `workspace/implementation/*.py` returns nothing. Storage is module-level dicts only, so `start.sh` re-invocation under `--isolation per-test-server` genuinely wipes state between all ~800 boots.
- **No orphan processes** left on the host.

Cosmetic note so it is not misread later: every `round.N.log` contains the token `Killed` exactly once, interleaved between the first test's name and its `PASSED [ 1%]` marker. This is the shell reporting the runner SIGKILLing the *initial* pre-boot server as per-test isolation swaps in a fresh one for test #1 — the test itself passes, it appears identically in all 8 rounds, and it is not a crash.

**Orchestrator re-verification (independent):** re-parsed all 8 `results.N.json` — each `passed=100 total=100 failed=0`, 100 rows apiece, 0 non-passed rows, identical 100-name set across every round; `def test_` count across `test_suite/` = 100.

## Step 8: Finalize PRD — SKIPPED — 2026-08-03T13:55:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites the test suite exercises, so there is no `<step_7_diff>` to patch against. No `PRD_FINALIZED.md` is produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-03T14:07:00.000Z

`PRD_COMPLETED.md` is written. Implementation was walked end to end (60 endpoints across 7 route modules, `services.py`, `calculations.py`, `validation.py`, `store.py`, `serializers.py`, `envelope.py`, `auth.py`).

### Counts
- **PRD.md**: 473 lines / 83,947 chars → **PRD_COMPLETED.md**: 473 lines / 96,611 chars (**+12,564 chars**, 0 line delta — every change is an in-paragraph insert or revision; section, subsection and table-row counts identical).
- **40 changed passages**: **35 ambiguity-pins**, **5 mismatch-revisions**. No new sections, no new paragraphs, no invented behavior.

### Changes
- §2.1 — revise — mismatch — "absent" → "absent or empty" header test (`auth.py:16`)
- §2.1 — revise — mismatch — ownership is on those six ops *and no others*; per-role compared field (Provider→`prescriber_provider_id`, Patient→`patient_id` on discontinue; `patient_id` only for Patient on subscription cancel); body `patient_id`/`subscription_id` never compared to caller (`auth.py:34`, `prescriptions.py:115-118`, `billing.py:114`, `surveillance.py:220`)
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 upper-alnum chars (`envelope.py:14`)
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not real time (`envelope.py:20`)
- §2.2 — insert — ambiguity — each resource object carries exactly its §3 fields + the four common ones (`serializers.py:80-89`)
- §2.2 — insert — ambiguity — which row is returned when an op writes several (escalate→rung, subscribe→subscription, triage→check-in) (`prescriptions.py:242`, `billing.py:52`, `surveillance.py:92`)
- §2.3 — insert — ambiguity — equal-`created_at` ties broken by write order, never by `id` (`store.py:195`)
- §2.3 — insert — ambiguity — unlisted query params ignored; filters compared as strings so an off-enum `status` returns an empty page, not 400; non-integer `limit`/`offset` → `ERR_VALIDATION`; empty string → default (`validation.py:178-221`)
- §2.4 — insert — ambiguity — `to_iso8601` mandatory/ISO-validated; `current_utc` echoes caller's exact string (`directory.py:31-33`)
- §2.4 — insert — ambiguity — client-supplied instants stored/echoed verbatim (any offset), derived instants rendered UTC-Z with fractional digits only if the source had them (`store.py:61-77`, `validation.py:106-115`)
- §2.5 — revise — mismatch — `version` bumps at most once per row per request; a row created then re-written in the same request stays at 1 (`store.py:172-190`)
- §2.7 rung 5 — insert — ambiguity — explicit JSON `null` == absent field; all enum failures route to `ERR_VALIDATION` (`validation.py:32-33`, `clinical.py:82-96`)
- §2.7 rung 6 — insert — ambiguity — per-operation body-reference resolution order; escalation's `second_signer_provider_id` is *not* resolved at this rung (`prescriptions.py:37-40`, `prescriptions.py:211`)
- §3.2 — insert — ambiguity — `comorbidity_count` recounted even on the stale-labs deferral (`clinical.py:99`)
- §3.3 — revise — mismatch — consult booking names "a `patient_id`", uncompared with the caller (`clinical.py:138-144`)
- §3.3 — insert — ambiguity — omitted `outcome_note` leaves the field as it stands (`clinical.py:205`)
- §3.3 — insert — ambiguity — reschedule tests `NO_SHOW` before suitability; no new `provider_id`; note survives (`clinical.py:221-235`)
- §3.4 — insert — ambiguity — consult-state error (rung 8) beats screening-eligibility (rung 9); no consult↔patient linkage; prescriber checked for existence only (`prescriptions.py:39-49`)
- §3.4 — insert — ambiguity — order creation writes `ROUTED` unconditionally from any prior axis value (`fulfillment.py:69`)
- §3.4 — insert — ambiguity — refill: axis test precedes clinical test, so held+undispensed → `ERR_INVALID_STATE` (`prescriptions.py:149-152`)
- §3.4 — insert — ambiguity — predecessor set taken pre-write; multiple `ACTIVE` all discontinued, newest id recorded (`prescriptions.py:51-80`)
- §3.5 — revise — mismatch — a below-threshold `second_signer_provider_id` is not "simply recorded": gate 4 still runs (`prescriptions.py:210`)
- §3.5 — insert — ambiguity — unknown signer → `ERR_PROVIDER_NOT_FOUND` at gate 4, after gates 1–3 (`prescriptions.py:211`)
- §3.5 — insert — ambiguity — hold on a `DISCONTINUED` prescription → `ERR_INVALID_STATE`; rung status tested first (`prescriptions.py:250-255`)
- §3.5 — insert — ambiguity — reduce likewise `ERR_INVALID_STATE`; three tests in order rung/prescription/floor (`prescriptions.py:268-275`)
- §3.6 — insert — ambiguity — filing imposes no prescription-state test; several PAs may coexist (`payer.py:30`)
- §3.6 — insert — ambiguity — authorisation status tested before prescription status; omitted `denial_reason` writes null (`payer.py:71-90`)
- §3.7 — insert — ambiguity — residual routing tie settled by lot record order (`services.py:256-259`)
- §3.7 — insert — ambiguity — `ERR_UNITS_EXCEED_LIMIT` reachable only via `units_per_cycle` (rung 5 catches >4); rung needs no linkage to the prescription and no status (`fulfillment.py:25-52`)
- §3.7 — insert — ambiguity — one shared cancellation routine, so unit restore + axis rewind fire on every cascade path (`services.py:150-170`)
- §3.8 — revise — mismatch — check-in names "a `patient_id`", uncompared; no prescription linkage/state test (`surveillance.py:32-33`)
- §3.8 — insert — ambiguity — `triaged_by_provider_id` is the raw `X-User-ID`, unvalidated; recompute precedes the cascade (`surveillance.py:81-87`)
- §3.8 — insert — ambiguity — hops 2–5 do not fire unless the prescription is `ACTIVE` (`services.py:176-177`)
- §3.8 — insert — ambiguity — resolve hops 2–3 fire only when `HELD`; resolution never recomputes the indices (`services.py:193-194`, `surveillance.py:103-109`)
- §3.8 — insert — ambiguity — `severity_index_since_dose_change` is 0 on an empty pool (`calculations.py:152`)
- §3.8 — insert — ambiguity — a recompute always refreshes `updated_at`/`version` even when neither index changes (`services.py:146`)
- §3.9 — insert — ambiguity — `period_start_at`/`period_end_at` inherit the anchor's rendering; resume-opened cycles use the clock's 3-digit form (`services.py:275`, `billing.py:105`, `billing.py:215`)
- §3.9 — insert — ambiguity — `payment_reference` validated but not persisted (`billing.py:194`)
- §3.9 — revise — mismatch — pause/cancel cascade voids *every* `OPEN`/`INVOICED` cycle in creation order, forfeiting each cycle's sessions before the next (`services.py:329-335`)
- §3.9 — insert — ambiguity — resume never tests the 60-day ceiling (`billing.py:97-105`)
- §3.9 — insert — ambiguity — subscription creation checks existence only, no patient↔prescription linkage or state (`billing.py:32-33`)
- §3.10 — revise — mismatch — "exactly one" cycle → cycles scanned in creation order, first match wins (`surveillance.py:143-150`)
- §3.10 — insert — ambiguity — session cancel imposes no subscription-status and no ownership test (`surveillance.py:218-232`)

**Orchestrator verification (independent):** `PRD_COMPLETED.md` = 473 lines (same as `PRD.md`); heading count 29 = 29; table-row count 94 = 94; 86 changed lines (43 replaced pairs) — consistent with 40 in-paragraph edits and no structural change.

---

## Pipeline complete

Steps 1–9 done (Step 8 skipped by its skip condition). Final state: 14 entities / 60 endpoints / 10 state machines / 9 calculations / 30 error codes; 100 tests; 8/8 sweep rounds at 100/100; 0 Step-7 deletions and 0 fixes of any kind; `PRD_COMPLETED.md` closes 35 ambiguities + 5 mismatches found by the full impl scan.
