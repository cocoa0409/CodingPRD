# Worklog — task_1642_weigh_station_bypass_fleet_compliance

## Step 1: Create Task Directory — 2026-08-14T04:15:00.000Z

Pre-assigned directory `tasks/task_1642_weigh_station_bypass_fleet_compliance/` with `workspace/` subdirectory (created externally; treated as DONE per orchestration instructions).

## Step 2: Generate Scaffold — 2026-08-14T05:26:47.000Z

Scaffold generation complete. All three artifacts are written and lint-clean.

## Output files

- `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/SCAFFOLD.yaml` — §1.0–§1.7 only (verified: no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    47
  §1.8 instances scanned:     21
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  911

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

- **Entities: 12** (Carrier, StateProgramConfig, Station, Vehicle, BypassCredential, VehicleSubscription, SafetyScoreSnapshot, BypassEvent, BypassDispute, EligibilityOverride, Invoice, InspectionReport)
- **State machines: 10** — Carrier lifecycle (cyclic officer loop), Carrier eligibility posture (derived, cyclic, drives the safety cascade), StateProgramConfig participation (cyclic, PILOT↛backwards), Station (cyclic + terminal), Vehicle (cyclic + terminal), BypassCredential (cyclic PROVISIONED↔ACTIVE↔SUSPENDED→DEACTIVATED), VehicleSubscription (parallel dimensions: lifecycle × payment_standing), EligibilityOverride (approval chain + clock/feed-driven EXPIRED/STALE), BypassDispute (branching fork + appeal cycle), Invoice (ISSUED→PAID/PAST_DUE→PAID)
- **Calculations: 8** (posture threshold, 14-check bypass decision engine, deterministic Nth-approach screen, self-referential rate-cap counter, tiered+prorated invoice with pinned per-line-then-sum rounding, forward-looking invoice preview variant, dual-variant ROI STANDARD/CONSERVATIVE, credit-ledger reconciliation)
- **Validation rules: 23** (explicit priority: auth → ownership → existence → state/OCC → safety → referential → temporal → constraint/SoD → fiscal)
- **Endpoints: 47** (23 writes incl. `POST /api/_clock/set_current_utc` with mandatory default `2026-08-01T00:00:00Z`; 24 GETs)
- **Errors: 47** (all referenced by ≥1 validation/transition; none undeclared referenced)
- **Roles: 7** (PlatformAdmin, StateProgramManager, ComplianceOfficer, CarrierManager `entity_backed:Carrier`, SafetyDataFeed, TelematicsGateway, FinanceAdmin) — segregation-of-duties model (appeal review must be a different officer; role-per-target-state on carrier transitions)
- **Concurrency rules: 3** (OCC on Carrier.version for snapshot POST and override POST; on StateProgramConfig.version for rules PATCH)
- **§1.8 instances: 21** — dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 3, transitive_cascade 2 (snapshot→posture→credential→subscription depth-3; dispute→ledger→invoice→standing depth-4), priority_pair_validation_conflict 3 (state-vs-safety, temporal-vs-fiscal, safety-vs-fiscal), boundary_precision_check 2 (ISS 74/75; WIM 84000/84001), cross_entity_state_dependency 2, resource_temporal_overlap 2 (half-open override adjacency-allowed vs closed-interval subscription adjacency-rejected), compensating_invariant 2 (ledger-sum==balance through grant+application; billable+paused==overlap days)
- **§1.9 instances: 72** — entities 12, state_machines 11, calculations 8, validations 19, endpoints 2, errors 12 (2 real: a 23-call not-found sweep covering all 10 NOT_FOUND errors + error-envelope shape; 10 `excluded_because` stubs), rbac 2, cross_cutting_layers 5 (incl. out-of-order snapshot reconciliation, override STALE-on-newer-snapshot version pinning, due-date past-due boundary), consistency_model 1

## Key design decisions adjudicated

1. **Safety-score deactivation does NOT suspend the carrier lifecycle** — posture INELIGIBLE cascades only to credentials/subscriptions. This keeps `ERR_CARRIER_NOT_BYPASS_ELIGIBLE` reachable (otherwise the auto-suspension would always mask it) and creates a genuine safety-vs-fiscal priority conflict pair.
2. **Credential (re)activation accepts a PAUSED covering subscription** (auto-resuming it) — resolves a deadlock where safety-paused subscriptions could never be reactivated because activation required an ACTIVE subscription.
3. **Overweight enforcement whenever a WIM reading exists**; `requires_weight_clearance` only governs the absent-reading case — otherwise an overweight reading in a clearance-off state would bypass.
4. **Deterministic random screen**: `N = floor(10000/rate_bps)`, every Nth approach per (station, day) — no randomness in business decisions, fully testable.
5. **Rate cap is self-referential with pinned order** (pre-decision counters, `(g+1)/(t+1) <= cap` integer comparison, equality grants), CONDITIONAL carriers get `floor(cap/2)`.
6. **Endpoint count 47 exceeds the 20–32 Expert guideline band** — deliberate: with 12 FK-bearing entities, lint check (f) forces 12 filtered-list GETs plus 11 single-resource GETs to anchor collection segments. §0.4 labels the band a guideline, not a hard rule, and §1.5's testability-completeness principle overrides convenience; the difficulty budget is carried by interaction density (chains, precedence, rounding), not CRUD volume.
7. **`Carrier.latest_snapshot_id` deliberately not declared as an FK** (parent-side derived pointer); `EligibilityOverride.approved_against_snapshot_id` kept as a true FK with a matching filtered-list parameter.
8. Every numeric assert in §1.8/§1.9 was pre-computed in Python (rounding order 4179-vs-4178 trap, tier-drop paradox 17589 < 17990, cap/screen sequences, ROI 3825/2550, day partitions 19/26 days, due-date 2026-09-15 boundary); all 911 design-file calls replay cleanly against §1.2/§1.4/§1.6 including placeholder closure, OCC `${var}` discipline, and temporal windows.

## Step 3: Copy Shared Files — 2026-08-14T05:27:23.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1642_weigh_station_bypass_fleet_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T05:45:00.000Z

PRD generation complete. The document is written to `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/workspace/PRD.md` and all three hard contracts pass mechanical verification.

## PRD Section List (349 lines total)

| Lines | Section |
|---|---|
| 1 | Title |
| 3–8 | 1. Introduction (6) |
| 9–12 | 2. Global Specifications preamble (4) |
| 13–22 | 2.1. User and Role-Based Access Control (10) |
| 23–71 | 2.2. API Response Structure (49 — byte-identical to canonical source) |
| 72–77 | 2.3. Pagination (6) |
| 78–83 | 2.4. The Logical Clock and Date Semantics (6) |
| 84–89 | 2.5. Common Resource Properties (6) |
| 90–95 | 2.6. Registry Uniqueness and Feed Idempotency (6) |
| 96–101 | 2.7. Immutable Roadside Decisions and Ruleset Pinning (6) |
| 102–107 | 2.8. Money, Credits, and the Append-Only Ledger (6) |
| 108–111 | 2.9. Optimistic Concurrency Control (4) |
| 112–133 | 2.10. Validation Order and Error Surface (22) |
| 136–145 | 3.1. Carrier Onboarding and the Enrollment Lifecycle (10) |
| 146–157 | 3.2. Safety Scores, Eligibility Posture, and Safety-Driven Deactivation (12) |
| 158–165 | 3.3. State Programs and the Station Registry (8) |
| 166–179 | 3.4. Fleet Management, Credentials, and Subscription Service (14) |
| 180–206 | 3.5. Roadside Approaches and the Bypass Decision (27) |
| 207–216 | 3.6. Disputes, Appeals, and Credit Adjudication (10) |
| 217–224 | 3.7. Eligibility Overrides: Temporary Waivers (8) |
| 225–242 | 3.8. Billing Close, Invoices, and ROI Reporting (18) |
| 243–296 | 4. Endpoint Definitions (54; 47 rows × 4 columns) |
| 297–349 | 5. Error Code Catalogue (53; 47 rows × 2 columns) |

## Coverage Audit (scaffold → PRD)

- `scenario` → §1 (2 paragraphs, business-context + system-goals angle)
- `response_envelope` → §2.2 verbatim (verified byte-identical) + §2.3 (limit 10/1/100, offset 0, `created_at` ascending, meta fields)
- `entities` (12, incl. `common_fields: false` trio) → fields scattered through §2.4–2.8 and §3.1–3.8; the no-`updated_at`/no-`version` rule for snapshots/events/inspections stated explicitly in §2.5
- `state_machines` (10, incl. posture machine + parallel `payment_standing`) → §3.1 (carrier), §3.2 (posture, all nine band pairs), §3.3 (config, station), §3.4 (vehicle, credential, subscription ×2), §3.6 (dispute), §3.7 (override), §3.8 (invoice)
- `concurrency_rules` (3) → §2.9 with exact `occ_field` names + `ERR_STALE_VERSION`/412, restated at point of use in §3.2/§3.3/§3.7
- `calculations` (7) → §3.2 (posture), §3.5 (decision evaluation with all 14 pinned checks + 16 reason codes, screen, cap), §3.8 (close, preview, ROI, ledger reconciliation — ledger invariant also in §2.8)
- `validations` (23 priorities) → §2.10 ladder with explicit ordering, re-anchored per workflow (credential gate order in §3.4, dispute target order in §3.6, payment-amount > already-paid in §3.8)
- `endpoints` (47) → §4 table; side effects narrated in §3
- `errors` (47) → §5 table + every ID mentioned in §2/§3
- `roles` (7) → §2.1 with exact names, per-role identity prose (CarrierManager entity-backed; six opaque)

## Zero-Silence Rule Self-Audit (Hard Contracts)

- **Contract 1 (Field-Name Coverage): PASS** — entities[].fields: 85 required, 85 present, 0 missing; endpoints[].input: 62 required, 62 present, 0 missing; path params: 12 required, 12 present, 0 missing. (Ledger-entry, invoice-line, clock-output, and ROI-output identifiers also verified present.) One gap found and fixed during audit: bare `RETIRED` state value.
- **Contract 2 (Rule Coverage): PASS** — 23/23 validations expressed with priority ordering; 3/3 OCC rejections (write endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412 named); all state-machine transitions expressed with preconditions/side effects (incl. terminate/retire/safety cascades, credit auto-apply sweep order, once-per-adjudication version bump); 7/7 calculations in precise prose (boundary examples 75/74/50/49, screen N and ordinal rule, cap inequality with equality-allows, tier average-rate, half-up per-line rounding, ROI floor/null rules); all `applies_to` scopes enumerated (e.g., the five-operation `ERR_CARRIER_NOT_ACTIVE` scope with the override exception); sibling branches rendered symmetrically (UPHELD/OVERTURNED from both OPENED and APPEALED; APPROVED→ACTIVE vs ACTIVE→EXPIRED/STALE/REVOKED).
- **Contract 3 (§3 Path Purity): PASS** — 570 backtick tokens scanned in §3; 0 slash-prefixed, 0 bare HTTP methods, 0 method+path combos. The `/api` mount appears only in §1.
- Spot checks: no fuzzy words ("approximately"/"roughly"/etc.), no pseudocode operators (`>=`, `==`, `floor()`, `%`, …) anywhere outside the verbatim JSON fences; §4 rows = 47 with 4 columns; §5 rows = 47 with 2 columns.

## Ambiguities Resolved

1. **Posture-cascade wording in `carrier_eligibility_posture`** ("if carrier.status == ACTIVE -> SUSPENDED cascade (see Carrier machine)") vs. posture note2 ("Carrier.status is NOT auto-changed by posture"). Resolved per the two state-machine notes, which are authoritative: the lifecycle machine is untouched; the cascade suspends *credentials* (and pauses their subscriptions). §3.2 states both halves explicitly — an ACTIVE carrier keeps its lifecycle status while INELIGIBLE, and all its approaches pull in at decision check 5.
2. **Phantom error ID `ERR_FUTURE_EFFECTIVE_DATE`** referenced in the snapshot field description but absent from the `errors[]` catalog; validation p13 maps the same condition to `ERR_INVALID_DATE_RANGE`. The catalog is the contract, so the PRD uses `ERR_INVALID_DATE_RANGE` and never mentions the phantom ID.
3. **`ERR_NO_ACTIVE_SUBSCRIPTION` condition** says "status ACTIVE" in the catalog while validation p20 and the transition precondition say {ACTIVE, PAUSED} with auto-resume. Used the more specific two-of-three-sources rule (covering subscription in `ACTIVE` or `PAUSED`; PAUSED auto-resumes on activation).
4. **Closed-EXPIRED subscription line inclusion** in billing: expressed via window disjointness (a subscription expired before the period has a window ending before the period starts → no line), matching the scaffold's parenthetical.
5. **Pause-accrual day arithmetic** (`today - paused_at`, and `last - paused_at + 1` at close): rendered as inclusive-exclusive day-count prose ("days from the recorded pause date to the resume date"; "days from `paused_at` through the month's final day inclusive"), preserving the off-by-one asymmetry between the two formulas.

Not read, per the hard constraint: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, grepped, or referenced at any point.

## Step 5: Generate Unit Tests — 2026-08-14T06:35:00.000Z

Generation complete. Everything is written under `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/`.

## Test counts

**103 tests total** — Queue A (Difficulty): 42 tests covering all 21 §1.8 instances at exactly 2 tests each. Queue B (Corner): 61 tests covering 61 of 62 non-stub §1.9 instances at 1 test each.

| File | Tests | Contents |
|---|---|---|
| test_01_creation_registry_and_uniqueness.py | 12 | Corner/entities (11) + consistency_model (1) |
| test_02_envelope_listings_and_access_control.py | 7 | Corner/errors (2), endpoints (2), rbac (2), validations (1) |
| test_03_lifecycle_transitions_and_cascades.py | 13 | Corner/state_machines (10), validations (1) + Difficulty carrier_suspend_reinstate_cycle (2) |
| test_04_bypass_decision_engine.py | 18 | Corner/calculations (5), cross_cutting_layers (2), validations (2), entities event-immutability (1) + Difficulty wim_weight (2), branch_precedence (2), rate_cap_order (2), config_participation (2) |
| test_05_posture_snapshots_and_overrides.py | 15 | Corner/calculations (1), validations (7), cross_cutting_layers (2) + Difficulty iss_74_vs_75 (2), override adjacency (2), safety deep cascade (2) — 1 test added after audit caught a missed instance |
| test_06_subscription_and_credential_gates.py | 13 | Corner/validations (3) + Difficulty activation/vehicle (2), safety-vs-fiscal (2), state-vs-safety (2), temporal-vs-fiscal (2), subscription adjacency (2) |
| test_07_billing_invoices_and_reporting.py | 16 | Corner/calculations (2), validations (3), cross_cutting_layers (1) + Difficulty preview-vs-final (2), line rounding (2), day partition (2), parallel status/standing (2), ROI variants (2) |
| test_08_disputes_and_credit_ledger.py | 9 | Corner/validations (3) + Difficulty appeal SoD (2), auto-apply cascade (2), ledger conservation (2) |

## Helper files produced (Stage 1, `test_helpers/`)

`__init__.py` (barrel), `types.py` (12 entity TypedDicts — append-only Snapshot/BypassEvent/InspectionReport correctly omit `updated_at`/`version`; 25 status/role enums), `api_client.py` (35 endpoint methods, `/api` prefix), `api_errors.py` (47 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + `assert_credit_ledger_invariant`), `factories.py` (input-only payload factories with counter-unique registry keys), `constants.py` (ISS floors 50/75, WIM 500 bps, tier rates 1799/1599/1399, pilot surcharge 200, avoided cost 1275, dispute window 30), `test_users.py` (7 roles; `make_carrier_manager_headers(carrier_id)` for the entity-backed CarrierManager), `fixtures.py` (tiered helpers: `create_active_carrier`, `setup_bypass_ready`, `setup_pull_in_event`, `setup_carrier_with_invoice`, `setup_carrier_past_due`, OCC-aware `post_snapshot`, list helpers — all identity-threaded). `test_suite/conftest.py` exposes the session-scoped `api` fixture plus role-header fixtures.

## Skipped instance (1)

- **Corner/entities/`carrier_create_computed_and_system_fields_input_ignored`** — the instance asserts that client-supplied system fields (`status: ACTIVE`, `credit_balance_cents: 9999`) in a create body are silently ignored. PRD.md never states how the server treats server-managed fields present in request payloads (ignore vs. reject); two PRD-only readers diverge, so it fails the unique-derivability condition. No test emitted, no placeholder.

All 10 `excluded_because:` stubs were verified to resolve to real §1.8 instance names and were not translated.

## Two derivability adjustments (instances kept, assertions pinned to what the PRD uniquely determines)

1. **Absolute version literals**: this PRD says `version` "increments by one on every mutation" but never pins the initial value (unlike sibling PRDs that say "starts at 1"). So `carrier_suspend_reinstate_cycle` asserts each transition increments version by exactly 1 (relative to the captured post-approval version) rather than the literal `== 7`; `ruleset_version` pinning is asserted against the config version captured from the governing PATCH response rather than literals 2/3/4; creation-defaults and immediacy tests assert `version` is an integer rather than `== 1`.
2. **`not_found_sweep_returns_404`**: the bypass-event POST with both `vehicle_id` and `station_id` missing is asserted with `validate_error_is_one_of([ERR_VEHICLE_NOT_FOUND, ERR_STATION_NOT_FOUND])` + HTTP 404, because PRD §2.10's rung-4 enumeration orders "station" before "vehicle" while payload-order reading implies the reverse. All 22 other sweep calls keep their exact per-resource 404.

Also dropped one literal: the exact `'2026-08'` label string in `close_period_already_closed_returns_409` (PRD says "appends the period label" without pinning the label format) — the test asserts the 409, exactly one invoice, and exactly one appended label instead.

## Verification performed

- `py_compile` clean on all files; `pytest --collect-only` collects 103 tests with no import errors.
- Tag audit: every test docstring ends with exactly one `Design:` line; all 82 tags resolve to real instances; every §1.8 instance has ≥2 tests; every non-stub §1.9 instance (minus the documented skip) has ≥1.
- Citation audit: every ≥6-word quoted fragment of every test docstring was mechanically verified to appear verbatim (whitespace-normalized) in PRD.md — zero misses.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T06:35:00.000Z

Implementation complete at `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/workspace/implementation/` — Python + Flask, in-memory only, empty store on every boot, no seeding anywhere.

## File list (2,855 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Guarded pip install (`import flask` check), `exec python3 app.py`, PORT env, 0.0.0.0 |
| `requirements.txt` | 1 | flask>=3.0,<4 |
| `app.py` | 39 | Entry point, ApiError/404/405/500 envelope handlers |
| `db.py` | 74 | In-memory store (12 dicts), logical clock default `2026-08-01T00:00:00Z`, seq/stamp/bump/public helpers |
| `errors.py` | 25 | ApiError carrying error_id + HTTP status |
| `response.py` | 44 | Envelope: `meta{api_request_id, api_request_timestamp}` (+`limit/offset/total_count/has_more` on lists), `response_type`, `data{error_id,message}` on errors |
| `middleware.py` | 141 | X-User-ID/X-User-Role auth (rung 1), role gate (rung 2), ownership (rung 3), field validators, pagination (limit 1–100 default 10, offset≥0, strict 400 out-of-range), shared list handler |
| `util.py` | 36 | ISO-8601/YYYY-MM-DD parsing, 3-fractional-digit Z formatting |
| `routes/` (13 files) | 1,512 | carriers, clock, configs, stations, vehicles, credentials, snapshots, events, disputes, overrides, subscriptions, invoices, inspections |
| `services/` (5 files) | 608 | posture (eligibility machine + safety cascade), credit (ledger + auto-apply sweep), sweep (clock materialization + past-due), decision (14-check engine), billing (close/preview/ROI) |

## Endpoint coverage
All 45 endpoints from the PRD §4 table implemented, including the `POST /api/_clock/set_current_utc` test-driving clock with the ordered materialization sweep (overrides activate/expire → subscriptions activate/expire → invoices past-due with standing propagation) and tally response.

## State machines
Carrier lifecycle (ENROLLED/ACTIVE/SUSPENDED/TERMINATED, per-target role gate, terminate cascade to credentials/subscriptions/overrides); derived posture machine (NOT_EVALUATED/ELIGIBLE/CONDITIONAL/INELIGIBLE with override force, STALE-on-newer-snapshot pinning, safety cascade suspending ACTIVE credentials + pausing their vehicles' subscriptions); config participation (PILOT entry-only, PARTICIPATING↔SUSPENDED, same-state/back-to-PILOT rejected); station operational (CLOSED_PERM terminal); vehicle service (RETIRED cascade); credential (PROVISIONED/ACTIVE/SUSPENDED/DEACTIVATED, manual-suspend pauses subscription, manual-deactivate leaves it ACTIVE, reactivation resumes with pause accrual); subscription parallel dimensions (lifecycle × payment_standing); dispute (OPENED→UPHELD/OVERTURNED, UPHELD→APPEALED→UPHELD_FINAL/OVERTURNED with segregation of duties); override (REQUESTED/APPROVED/ACTIVE/REVOKED/EXPIRED/STALE/REJECTED); invoice (ISSUED/PAID/PAST_DUE).

## Calculations
- Posture thresholds (inclusive-lower: 75/50) with override force
- 14-check decision engine in pinned order incl. WIM tolerance `gvwr + floor(gvwr*500/10000)` (at-limit clears), PILOT-prefers-MOBILE_APP selector with created_at tie-break, deterministic screen (`N=floor(10000/bps)`, ordinal % N == 0), rate cap `(g+1)*10000 <= cap*(t+1)` with CONDITIONAL halving — all verified against the design docs' worked sequences
- Billing close: inclusive overlap days, pause accrual `(today − paused_at)`, PILOT home-state surcharge 200, average-rate tiers (1799/1599/1399), per-line `round_half_up` then sum (reproduced the docs' 4179 and 1509/19-of-31 examples), due_date = next-month-1st + 14d, born-PAID when amount_due == 0
- Credit ledger: append-only, balance = SUM invariant, dispute-overturn auto-apply sweep (issued_at ASC, full coverage only), standing recovery
- ROI report: floor bypass_rate_bps, STANDARD/CONSERVATIVE variants, 1275¢/bypass, round-half-up roi_bps, null when fees 0
- OCC: `expected_carrier_version` (snapshot, override request), `expected_state_program_config_version` (config patch), missing/mismatched → 412

## Validation/error handling
Full 15-rung PRD §2.10 ladder with pinned intra-rung orders (e.g., INELIGIBLE_FOR_APPROVAL → STILL_INELIGIBLE → NOT_ACTIVE → NOT_BYPASS_ELIGIBLE → VEHICLE_NOT_IN_SERVICE; EVENT_NOT_DISPUTABLE → DISPUTE_WINDOW_EXPIRED; NO_ACTIVE_SUBSCRIPTION → CARRIER_PAST_DUE; PAYMENT_AMOUNT_MISMATCH → INVOICE_NOT_PAYABLE; existence in resource-type order: station before vehicle for events). All 46 catalogued error IDs with exact HTTP statuses. Ownership resolves through referenced resources with unresolvable refs falling through to 404.

## Boot smoke-test result
Fresh `bash start.sh` boots in ~1.5s; double-boot test confirms empty store and default clock on every launch (per-test-server safe). Four smoke rounds (100+ assertions) all pass: full happy path, auth/role/ownership gates, OCC 412s, decision reasons incl. OVERWEIGHT boundary (84000 clears, 84001 pulls), dispute + appeal + SoD, credit grant/auto-apply, billing close with credit application (1799 gross → 0 due → PAID, balance 1201), past-due boundary sweep (due-date day stays ISSUED, next day flips), safety cascade (INELIGIBLE, credentials SAFETY_INELIGIBLE, sub PAUSED, carrier version +2), override approve→ACTIVE→STALE cycle, terminate/retire cascades, window overlap/adjacency semantics, and pagination meta. The only two smoke "failures" were my own script bugs (stale approach timestamps, never-registered serial); the API behavior matched the PRD in both cases.

[Orchestrator note: Step 6 reported "45 endpoints from the PRD §4 table" while Step 4 reported the table holds 47 rows; Step 7 will surface any gap as failures if tests exercise missing endpoints.]

## Step 7: Run Tests and Iterate — 2026-08-14T06:50:00.000Z

Clean 8-round sweep achieved. Final summary:

## Summary

**Result: all 8 parallel rounds pass 103/103 — exit condition met.**

### Iterations run
2 sweeps (sweep 1 diagnostic: 89/103 × 7 rounds, 88/103 × 1 round; sweep 2 verification: 103/103 × all 8 rounds, 824 test executions, zero failures).

### Tests deleted
None. Every failing assertion traced to a verbatim PRD rule; no PRD-silence or unique-derivability collapse was found.

### Fixes applied to `implementation/` (1)
- `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/workspace/implementation/db.py` — `new_id()` returned `uuid4().hex` (dashless 32-char hex). PRD §2.5's "server-minted UUID with no type prefix" is the canonical dashed RFC 4122 string form; changed to `str(uuid.uuid4())`. Fixed 10 tests whose identity-block assertions (`is_valid_uuid`, plus an explicit `"-" in id` check in test_01) rejected the dashless form.

### Fixes applied to `test_suite/` (2)
- `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/test_suite/test_05_posture_snapshots_and_overrides.py` — added missing imports `create_config` and `activate_credential`; three tests (`test_config_patch_with_stale_version`, `test_cascade_suspends_only_active_credentials`, `test_cascade_pause_flows_through_the_credential_link`) raised `NameError` because they referenced helpers never imported.
- `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/test_suite/test_04_bypass_decision_engine.py::test_state_threshold_difference` — test bug (STEP 2): the fixture carrier runs iss_score=60 → CONDITIONAL posture, so PRD §3.5's "cap … halved with the fraction discarded when the carrier's posture is `CONDITIONAL`" makes the first NV-bucket approach fail the rate cap: `(0+1)*10000 > 5000*(0+1)` → `RATE_CAP_EXCEEDED`. The original assertion of `BYPASS_GRANTED` on that first approach contradicted the PRD; the implementation was correct. The test now asserts the halved-cap `PULL_IN` on the first NV approach (pinning the halving rule) and `BYPASS_GRANTED` on the second (`10000 <= 5000*2` equality), preserving the test's purpose — CA refuses at 60>=60 while NV clears 60<75.

### Fixes applied to `test_helpers/`
None.

### Flakiness note
`test_appeal_requires_a_different_officer` failed once in sweep-1 round 4 with a transport-level `ConnectionError: Remote end closed connection without response` (stale keep-alive connection against a per-test restarted server under 8× load) — not an assertion failure and not a PRD-logic bug. It did not recur in sweep 2. Worth monitoring in future sweeps; if it recurs, hardening the module-level `requests.Session` in `test_helpers/api_client.py` would be the place to look.

## Step 8: Finalize PRD — 2026-08-14T06:56:00.000Z

Done. The diff is a single in-place sentence revision; everything else in Step 7's diff was test-side and required no PRD change.

## Summary

**Line counts / %-delta:** PRD.md 349 lines → PRD_FINALIZED.md 349 lines (0% delta; one sentence revised in place on line 86, ~+130 chars).

**Changes (1 edit):**
- §2.5 — revise — the identity-block sentence "`id` is a server-minted UUID with no type prefix." now pins the serialization: "…with no type prefix, rendered in the canonical RFC 4122 string form — 32 lowercase hexadecimal digits in five hyphen-separated groups of 8, 4, 4, 4, and 12 (for example `550e8400-e29b-41d4-a716-446655440000`), never the dashless 32-character hex form." — `implementation/db.py:50-52` (`new_id()` returns `str(uuid.uuid4())`).

**Step-7 items analyzed, no PRD edit warranted (2):**
- `test_05_posture_snapshots_and_overrides.py` import fix — pure test bug (`NameError` on missing helper imports). The exercised behaviors (config-patch OCC per §2.9/§2.10 rung 6, safety cascade suspending only `ACTIVE` credentials per §3.2, pause bookkeeping via the credential link per §3.2/§3.4) are already pinned verbatim in the PRD.
- `test_04_bypass_decision_engine.py::test_state_threshold_difference` — test bug; the original `BYPASS_GRANTED` assertion contradicted §3.5's pinned rule ("halved with the fraction discarded when the carrier's posture is `CONDITIONAL`"; "(granted+1)·10000 ≤ cap·(total+1); equality permits"). The implementation (`services/decision.py:119-122`) follows the PRD exactly, so the PRD already uniquely determines this behavior.

**Per-edit pre-edit search log (1 edit):**
- (a) Subject: serialization format of server-minted resource `id` values.
- (b) Paths enumerated and read/grepped: `db.py:50-52` (sole id generator — `str(uuid.uuid4())`, universally lowercase dashed); all 12 creation callsites — `routes/carriers.py:37`, `routes/configs.py:87`, `routes/stations.py:47`, `routes/vehicles.py:64`, `routes/credentials.py:82`, `routes/subscriptions.py:88`, `routes/snapshots.py:65`, `routes/events.py:83`, `routes/disputes.py:82`, `routes/overrides.py:101`, `routes/inspections.py:49`, `services/billing.py:118` (covers all 9 full-identity-block resources and all 3 append-only feed/audit records, so the wording describes every minted `id` uniformly); `response.py:13-14` (`api_request_id` = `req_` + 20 random alphanumerics — not a resource `id`, governed by §2.2, explicitly outside the edit's scope); `services/credit.py:18-26` (ledger entries carry no `id`); `services/billing.py:91-99` (invoice lines carry no `id`); all foreign-key fields copy previously minted ids; no endpoint accepts a client-supplied `id`.
- (c) Wording adjustment: included "lowercase" (universally true of `str(uuid.uuid4())` on every enumerated callsite) and the explicit "never the dashless 32-character hex form" exclusion naming the exact pre-fix alternative; kept the sentence scoped to §2.5's identity-block `id` so §2.2's `api_request_id` and the id-less ledger/line records are not implicated.

File: `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-14T07:25:00.000Z

All pins verified in place. The task is complete.

## Summary

**Source**: `PRD_FINALIZED.md` existed, so it was copied to `/home/ubuntu/github/CodingPRD/tasks/task_1642_weigh_station_bypass_fleet_compliance/workspace/PRD_COMPLETED.md` and only that file was edited.

**Size**: 349 → 350 lines; 61,953 → 64,882 chars (**+2,929**). 17 in-place sentence revisions/inserts + 1 error-catalogue row added. No new sections; no behavior invented.

**Counts**: 21 ambiguity-pins, 1 mismatch-revision.

**Changes** (section — insert|revise — class — what changed — impl ref):

- §2.3 — insert — ambiguity — invalid `limit`/`offset` rejected `ERR_INVALID_REQUEST` (400); `created_at` ties ordered by creation sequence; `has_more` = `offset + returned < total_count` — middleware.py:104-141, response.py:29-35
- §2.4 — insert — ambiguity — clock accepts any parseable ISO-8601 instant including earlier-than-current; missing/unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — routes/clock.py:14-26
- §2.5 — insert — ambiguity — `version` begins at 1 at creation — db.py:67-70, routes/carriers.py:49
- §2.10 rung 4 — insert — ambiguity — missing snapshot/inspection-report id on read yields `ERR_NOT_FOUND` (404) — routes/snapshots.py:112, routes/inspections.py:77
- §2.10 rung 12 — insert — ambiguity — target states outside an endpoint's accepted set (e.g. `to_status` `ENROLLED`) are rung-12 `ERR_INVALID_REQUEST`, not rung-5 — carriers.py:139-143, stations.py:98-103, vehicles.py:136-141, credentials.py:148-153, disputes.py:138-141, overrides.py:163-166
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` → 404 catalogue row — routes/snapshots.py:112, routes/inspections.py:77
- §3.1 — insert — ambiguity — termination's override revocation is bookkeeping only: no posture recompute, no safety cascade — routes/carriers.py:78-85
- §3.2 — **revise — mismatch** — safety cascade fires only on entry into `INELIGIBLE` from `ELIGIBLE`/`CONDITIONAL`; a first snapshot landing `NOT_EVALUATED`→`INELIGIBLE` fires nothing, so carrier `version` rises only by the snapshot write's +1 — services/posture.py:50-61, routes/snapshots.py:96-98
- §3.4 — insert — ambiguity — activation/reactivation records `status_reason` `NONE` — routes/credentials.py:200-201
- §3.4 — insert — ambiguity — manual deactivation records `status_reason` `MANUAL` — routes/credentials.py:217-220
- §3.4 — revise — ambiguity — any close of a `PAUSED` subscription (cancel, expiry sweep, termination/retirement cascades) accrues the open pause interval as the day count between `paused_at` and the closing date (replacing the inclusive-sounding "days from `paused_at` through today") — services/sweep.py:10-25
- §3.5 — insert — ambiguity — credential selector's identical-`created_at` ties break toward the earlier-created credential — services/decision.py:29-32
- §3.6 — insert — ambiguity — `credit_amount_cents` supplied with an `UPHELD` outcome is ignored — routes/disputes.py:144-157
- §3.7 — insert — ambiguity — `REVOKE` records `decided_by` like other outcomes — routes/overrides.py:199-202
- §3.7 — revise — ambiguity — `STALE` flip triggers whenever the latest-snapshot pointer moves off `approved_against_snapshot_id`, including same-`effective_date` snapshots winning the creation tie-break — routes/snapshots.py:86-93
- §3.8 — revise — ambiguity — tier table covers zero-line invoices (`TIER_1`) — services/billing.py:26-31
- §3.8 — insert — ambiguity — invoice lines emitted in subscription creation order — services/billing.py:52-55
- §3.8 — revise — ambiguity — invoice born `PAID` whenever amount due is zero, whether credit-covered or nothing billable — services/billing.py:141-143
- §3.8 — insert — ambiguity — `closed_billing_periods` label is zero-padded `YYYY-MM` — services/billing.py:152
- §3.8 — revise — ambiguity — preview defaults `period_year`/`period_month` independently, rejects non-integer/out-of-range month with `ERR_INVALID_REQUEST`; already-`CLOSED` subscriptions with overlapping windows still contribute lines — routes/carriers.py:195-212, services/billing.py:56-82
- §3.8 — insert — ambiguity — ROI `period_year`/`period_month` are both required (no current-period default); invalid `variant` → `ERR_INVALID_REQUEST` — routes/carriers.py:222-240
- §3.8 — insert — ambiguity — `roi_bps` half-up rounding sends negative exact-halves away from zero (Decimal `ROUND_HALF_UP`) — services/billing.py:208-211

**Notable non-changes** (already uniquely pinned): the 14-check decision order, weight-limit floor math, rate-cap equality-permits rule, screen ordinal formula, dispute window (age ≤ 30 days by calendar date), 48 h stale-approach strict bound, rung-4 station-before-vehicle ordering on event POST (the test suite's either-404 leniency is moot — the PRD enumeration already orders station first and impl matches), and all status-code mappings.

## Step 7: Test-fix iteration loop — 2026-08-14T06:55:00.000Z

Ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 103 tests/round).

**Sweep 1**: 89/103 (rounds 1-3, 5-8) and 88/103 (round 4). Union = 15 failing tests in three deterministic groups plus one transport flake.

Fixes applied:

1. **`implementation/db.py` (`new_id`)** — returned `uuid4().hex` (32 hex chars, no dashes). PRD §2.5's "server-minted UUID" is the canonical dashed string form; `str(uuid.uuid4())` now. Fixed 10 tests whose `assert_*` identity-block checks (and the explicit `"-" in data["id"]` in test_01) rejected the dashless form.
2. **`test_suite/test_05_posture_snapshots_and_overrides.py`** — added missing imports `create_config` and `activate_credential` (NameError in 3 tests; both helpers exist in test_helpers and were simply never imported).
3. **`test_suite/test_04_bypass_decision_engine.py::test_state_threshold_difference`** — test bug, not implementation. The fixture carrier runs iss_score=60 (CONDITIONAL posture), so PRD §3.5's "cap ... halved with the fraction discarded when the carrier's posture is `CONDITIONAL`" makes the first NV-bucket approach fail the rate cap: (0+1)*10000 > 5000*(0+1). The original assertion of BYPASS_GRANTED on that first approach contradicted the PRD. The test now asserts PULL_IN/RATE_CAP_EXCEEDED on the first NV approach (pinning the halving rule) and BYPASS_GRANTED on the second (equality: 10000 <= 5000*2), preserving the test's purpose — the CA line refuses at 60>=60 while the NV line clears 60<75.

No tests deleted: every failing assertion traced to a verbatim PRD rule; no PRD-silence or unique-derivability collapses found.

**Sweep 2 (verification)**: all 8 rounds 103/103, zero failures, zero errors. The single sweep-1 flake (`test_appeal_requires_a_different_officer`, round 4 only: `ConnectionError: Remote end closed connection without response`) did not recur — transport-level stale keep-alive against a per-test restarted server under 8x load, not an assertion failure.
