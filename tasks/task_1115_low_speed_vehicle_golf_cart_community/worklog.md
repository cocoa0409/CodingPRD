# Worklog — task_1115_low_speed_vehicle_golf_cart_community

## Step 1: Create task directory — 2026-08-10T17:46:00.000Z

Task directory `tasks/task_1115_low_speed_vehicle_golf_cart_community/` and its `workspace/` subdirectory were pre-assigned and pre-created by the orchestrating harness (Step 1 auto-index scan skipped per instructions). Directory confirmed empty and ready.

## Step 2: Generate scaffold — 2026-08-10T18:15:00.000Z

All three scaffold artifacts are written, parse as valid YAML, and pass the skill's lint cleanly.

### Files written

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1007 | §1.0–§1.7 (no difficulty/corner keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 779 | single top key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 789 | single top key `scaffold_corner_design` |

### Section/rule/instance counts

- **SCAFFOLD.yaml**: 13 entities, 12 state machines, 6 calculations, 10 ordered validations, 67 endpoints, 24 error codes, 6 roles, 2 OCC concurrency rules; fixed §1.0 envelope verbatim; complexity profile = compliance/audit × temporal-windowing, flat topology, cyclic state shape, peer roles, immediate consistency.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: all 9 rules, 23 instances total — dual_variant_calc 2, combinatorial_formula 3 (one per mode a/b/c), non_linear_state_machine 2, transitive_cascade 2 (depth 3 and depth 2), priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.
- **SCAFFOLD_CORNER_DESIGN.yaml**: all 9 taxonomy sections; 40 active instances + 4 `excluded_because` stubs (all resolving to real §1.8 names).

### Lint result (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
515 calls scanned, 0 violations. Self-audit: zero banned concurrency vocabulary, 67/67 instance names unique across both files, every error code referenced by a validation or transition, every `grounds:` reference resolves into §1.1–§1.7.

### Difficulty levers applied (per the "harder than expert" directive)

1. Dual-variant calcs on two domains: registration fee (provisional 16560 vs finalized 19000) and renewal compliance score (provisional 97 vs audited 92).
2. Combinatorial formulas in all three modes: (a) tiered fee with cap+floor+seat surcharge+program flag branch; (b) inspection score round-per-component-then-sum (all-84 → 83.99); (c) late-renewal fee with pinned fee→tier→late→cap evaluation order.
3. Non-linear machines: VehicleRegistration double cycle (ACTIVE↔RENEWAL_PENDING, ACTIVE↔SUSPENDED); PermitHolder eligibility_status × compliance_status parallel dimensions.
4. Transitive cascades: violation uphold → points → BARRED → registrations SUSPENDED → route passes REVOKED (depth 3); station offline → reservations CANCELLED → wallet refunds (depth 2).
5. Priority conflicts, three category pairs: state×fiscal, safety×temporal, temporal×fiscal.
6. Boundary precision: age == 16 passes vs one-day-under fails; score == 70.00 passes vs 69.00 fails; wallet == total_due drains to exactly 0.
7. Cross-entity state gates: RoutePass→Registration, Registration→PermitHolder, ChargingReservation→ChargingStation.
8. Temporal overlap with three interval semantics: half-open route passes, closed+15min-buffer charging, closed-no-buffer dispatch.
9. Compensating invariants: wallet cents conserved across book+cancel; fleet checked-out count conserved across checkout+return.

All formula-derived assert values precomputed by executing §1.3 formulas in Python. One self-consistency fix mid-authoring: registration REVOKED transition split into four per-from-state transitions so `from:` matches preconditions.

(Note: first Step-2 subagent attempt returned a design plan without writing files; a bounded retry subagent produced all three artifacts above.)

## Step 3: Copy shared files — 2026-08-10T18:16:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1115_low_speed_vehicle_golf_cart_community/workspace/INSTRUCTION.md` (bash-only step).

## Step 4: Generate PRD — 2026-08-10T18:45:00.000Z

The PRD is complete and verified. Final summary:

### Output
- **Path**: `workspace/PRD.md`
- **Size**: 335 lines / 7,237 words / 52,211 bytes

### Section list
- **§1. Introduction** — 2 paragraphs (business context + the two design tensions: audit cascades and heterogeneous interval semantics)
- **§2. Global Specifications** (11 subsections): 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 The Logical Clock and Time-Driven Transitions; 2.5 Common Resource Properties and Mutation Semantics; 2.6 Request Validation Pipeline and Error Precedence (10 ordered stages, first-failure-wins); 2.7 Optimistic Concurrency Control; 2.8 Money, Scores, and Rounding Discipline; 2.9 The Holder Wallet as a Prepaid Ledger; 2.10 Interval and Overlap Semantics; 2.11 Cascading Consistency
- **§3. Business Logic & Workflows** (9 subsections): Community Setup; Permit Holder Onboarding and the Two Standing Dimensions; Vehicles, Equipment, and Registration Drafting; Safety Inspections and Scored Outcomes; Insurance and Registration Activation; The Renewal Cycle; Street Designation and Route Passes; Charging Infrastructure and the Shared Fleet; Violations, Points, and Enforcement Cascades
- **§4. Endpoint Definitions** — 67-row table (Method/Path/Description/Authorized Roles only)
- **§5. Error Code Catalogue** — 24-row table (Error ID/HTTP Status only); document ends here, no audit footer

### Hard-contract results
- **Contract 1 (Field-Name Coverage): PASS** — 88 required names, 88 present, 0 missing (two passes; first pass caught `status`/`designation_status`, repaired in §2.5/§3.7)
- **Contract 3 (§3 Path Purity): PASS** — 403 backticked tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos
- Mechanical extras: all 24 error IDs appear in pre-§5 prose; all 40 state/enum values present; zero operator-syntax and zero fuzzy-word hits in prose (the two regex hits were "turnaround" false positives)

### Zero-Silence self-audit (scaffold §1.1–§1.7 → PRD)
- **§1.1 entities**: every field named in backticks with type/default/constraint content
- **§1.2 state machines**: all 12 machines, every transition with from/to states, preconditions paired to error IDs, and every side effect (incl. cascades, station-offline refunds, maintenance dispatch cancellations, FAILED-inspection suspension, no-resurrection rules)
- **§1.2.1 concurrency (2 OCC rules)**: §2.7 names write operation, OCC field, parent `version` match semantics, `ERR_STALE_VERSION`/412, and the "no other endpoint accepts a version field" exclusion
- **§1.3 calculations (6)**: annual fee (both variants, all 8 constants, per-step half-up rounding, base floor), late fee (pinned fee→tier→band→cap order), inspection score (all 8 weights, per-component round-then-sum, 70.00 inclusive), renewal score (both variants, 180/365 recency, 30-day aged-FILED half weight, 70 inclusive, floor 0), points standing (730-day window, 3/4–11/12 thresholds), charging fee (ceil minutes × rate, 200-cent floor) — all passing the reconstruction test
- **§1.4 validations**: all 10 priorities rendered as an explicit ordered pipeline in §2.6 with per-stage error IDs
- **§1.5 endpoints**: all 67 in §4 with exact role lists; side effects woven into §3 narratives; creation 201 / modification 200 rule stated
- **§1.6 errors**: all 24 in §5 table + all 24 trigger conditions in §2/§3 prose
- **§1.7 roles**: all 6 named in §2.1 with identity translation — `PermitHolder` entity-backed, the other five opaque

The withheld difficulty/corner index files were never opened; the PRD was generated solely from `SCAFFOLD.yaml`, the skill spec, and its two reference files.

## Step 5: Generate unit tests — 2026-08-10T19:05:00.000Z

All done. Final summary:

### Summary

Generated complete test infrastructure and test suite for `task_1115_low_speed_vehicle_golf_cart_community`, translating exactly the two design indices (no freelance SCAFFOLD walk).

#### File inventory (line counts)
**test_helpers/ (9 files, 1392 lines):**
- `types.py` (333) — 13 entity TypedDicts, 17 status/role enums; all entities carry full common fields per PRD §2.5
- `api_client.py` (219) — `ApiClient(GenericApiClient)` with 66 endpoint methods covering every PRD §4 endpoint incl. `/_clock/set_current_utc`
- `api_errors.py` (61) — 24 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` (182) — per-entity `assert_*` plus `assert_holder_invariants` (wallet ≥ 0, points↔standing consistency)
- `factories.py` (212) — 16 payload factories, input fields only
- `constants.py` (90) — fee/late-fee/inspection/renewal/points/charging/fleet constants, community defaults, startup clock
- `test_users.py` (27) — 6 role headers + mandatory `make_permit_holder_headers(user_id)` builder for the entity-backed PermitHolder role
- `fixtures.py` (269) — composite helpers across all 5 tiers: `create_eligible_holder`, `deposit` (OCC-threaded), `setup_activation_ready_registration`, `setup_active_registration`, `setup_route/station/reservation/fleet/dispatch`, `file_and_uphold_violation`, `setup_barred_holder`, `set_clock`
- `__init__.py` (19) — barrel export

**test_suite/ (14 files, 2596 lines):** `conftest.py` (45) + 13 test files organized by concern (fee/score variants, combinatorial formulas, state machines, cascades, validation-pipeline priority, boundary precision, cross-entity gates, temporal overlap, compensating invariants, entities/envelope, state-machine corners, validations/errors, calculations+RBAC+OCC+consistency).

#### Test counts
- **Queue A (Difficulty): 46 tests, 23/23 instances covered at exactly 2 tests each** (target ≥2 met)
- **Queue B (Corner): 40 tests, 40/40 non-stub instances covered at ≥1 test each**
- Total: 86 test functions

#### Skip list
No instance was skipped for PRD-coverage/derivability reasons — all 63 non-stub instances passed the two-condition filter (priority-pair tests are legitimate because PRD §2.6 explicitly pins the short-circuit pipeline order). The 4 `excluded_because:` stubs were not translated (per spec); all four cross-references resolve to real difficulty instances:
- `registration_renewal_cycle_covered` → `registration_cyclic_renewal_and_suspension` OK
- `provisional_fee_floor_covered` → `registration_fee_tiered_equipment_multiplier_floor` OK
- `cascade_coverage_covered` → `violation_uphold_cascade_to_route_pass_revocation` OK
- `dual_variant_coverage_covered` → `registration_fee_provisional_vs_finalized_fleet_discount` OK

#### Verification results
- `python3 -m py_compile`: **all 23 files pass**
- AST-based tag audit: **PASS** — every one of 86 tests carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, every tag resolves to a real instance with matching rule_id/section, no tag points to a stub, no `skip`/`skipif`/`xfail` anywhere
- PRD citation audit (C1 verbatim grep of `workspace/PRD.md`): **PASS** — 138 quoted PRD sentences all survive literal whitespace-normalized grep
- Module import check: all 14 test-suite modules import cleanly against `test_helpers`

## Step 6: Generate implementation — 2026-08-10T19:05:00.000Z

All verification complete. Here is the summary.

### Summary

Complete Python + Flask implementation generated at `workspace/implementation/`.

#### File inventory (line counts)

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 62 |
| `db.py` | 89 |
| `errors.py` | 105 |
| `middleware.py` | 68 |
| `response.py` | 55 |
| `services/calc.py` | 237 |
| `services/engine.py` | 120 |
| `services/serializers.py` | 214 |
| `services/validate.py` | 149 |
| `routes/communities.py` | 121 |
| `routes/permit_holders.py` | 175 |
| `routes/vehicles.py` | 96 |
| `routes/registrations.py` | 294 |
| `routes/inspections.py` | 123 |
| `routes/insurance.py` | 101 |
| `routes/routes_passes.py` | 194 |
| `routes/charging.py` | 217 |
| `routes/fleet.py` | 254 |
| `routes/violations.py` | 117 |
| `routes/clock.py` | 22 |
| **Total** | **2824** |

#### Endpoints: 67 implemented / 67 declared
All (method, path) pairs from SCAFFOLD §1.5 / PRD §4 including `POST /_clock/set_current_utc`. (Orchestrator re-verified post-hoc: 67 declared route pairs vs 67 registered `@bp.<method>` handlers — exact MATCH, no missing, no extras.)

#### Key behaviors verified via live E2E exercises
- **Envelope/auth**: `meta.api_request_id` (`req_…`), `api_request_timestamp` with 3 fractional digits; `response_type` object/array/error; error body `{error_id, message}`; 401 unauthenticated shape confirmed on smoke boot.
- **Logical clock**: boots at exactly `2026-05-01T00:00:00.000Z`; `set_current_utc` evaluates all six time-driven transitions (registration expiry/grace, pass completion, reservation completion, dispatch OVERDUE, policy date-based expiry).
- **Fees**: provisional vs finalized variants; per-multiplication round-half-up; seat surcharge past 4; base floor; multiplier cap 1.20; late fee tiers A/B with bands 30/60/grace and 2x cap — all confirmed numerically (e.g. LSV 8-equipment 6-seat: provisional 18400, finalized 19000; late band-1 tier B: 2500 + 19000 = 21500).
- **Inspection scoring**: per-component round-half-up to 2dp then sum (all-84 → 83.99, not 84.00); 70.00 inclusive pass; FAILED finalize suspends ACTIVE registration and revokes its ACTIVE passes; activate/reinstate gated on latest finalized PASSED.
- **Renewal**: in-window (both bounds inclusive) vs late-grace (lower exclusive, upper inclusive); audited score includes FILED violations >30 days old at 0.5 weight; fail audit → SUSPENDED without debit; pass → expiry +365d and debit.
- **Cascades**: holder revoke → registrations REVOKED → passes REVOKED; BARRED flip → ACTIVE registrations SUSPENDED → passes REVOKED; dismissal lowers standing without reinstatement; station offline → future BOOKED reservations CANCELLED + wallet refund; maintenance → future BOOKED dispatches CANCELLED.
- **Intervals**: route-pass half-open (adjacency allowed, true overlap 409); charging closed + 15-min buffer per (station, slot); dispatch closed with adjacency-as-conflict; end ≤ start → 400.
- **Wallet**: debit at activate/finalize/book/return; equality sufficient; 402 on shortfall; full refund on cancel/offline cascade; OCC `expected_permit_holder_version` / `expected_community_version` → 412.
- **RBAC**: six roles; PermitHolder ownership checks on target and payload; Anonymous allowed only on `POST /api/permit-holders`.

#### Boot checks
- `bash -n start.sh` parses; all 21 `.py` files compile under `python3 -m py_compile`; `requirements.txt` exists; `start.sh` is executable, foreground (`exec python3 app.py`), binds 0.0.0.0, reads `$PORT` (default 10000), guards pip install behind a flask-import check.
- Smoke boot on a free port succeeded: unauthenticated GET returned HTTP 401 with the exact error envelope, then the process was killed. No seeding anywhere — all stores start as empty dicts; the clock is the only initialized state (per PRD §2.4).

## Step 7: Test-fix iteration loop — 2026-08-10T20:30:00.000Z

Iteration 1 sweep (8 parallel rounds): 76/86 in every round; 10 distinct failures, all deterministic.
Diagnoses per the PRD-first protocol:

- test_helpers/api_errors.py: added missing `ERR_REGISTRATION_NOT_ACTIVE` (PRD §2.6 stage 8 + §3.7 verbatim, HTTP 422).
- test_helpers/assertions.py: added `assert_instant_equal` (PRD pins instants for `valid_from`/`expiry_date`, not serialization).
- test_10 `test_system_fields_server_minted_on_create`: created_at expected string fixed to `2026-05-01T00:00:00.000Z` (PRD §2.5 mandates three fractional digits).
- test_13 `test_activation_visible_immediately_in_response`: valid_from/expiry_date switched to instant comparison.
- test_11 `test_registration_expires_via_clock`: expiry_date instant comparison (2027-05-01 correct).
- test_11 `test_registration_initial_state_draft`: expected provisional fee corrected 7500 -> 7800 (default factory cart has 2 equipment items; PRD §3.5: 7500*1.04).
- test_01/test_03 renewal expiry assertions: expected 2028-05-01 corrected to 2028-04-30 (PRD §3.6 "+365 days" across 2028-02-29).
- test_02 `_setup_cf1`: 0-equipment GOLF_CART violates PRD §3.3 class minimum; cart A now declares headlights+brake lights (floor still binds: 7800*0.9=7020 -> max 7500).
- test_08 `test_start_exactly_at_buffer_boundary_legal` renamed to `..._rejected`: PRD §2.10 "touches" = collision at the exact buffer boundary; now asserts ERR_CHARGING_OVERLAP 409.
- test_05 restart flake (15s in-plugin poll under 8-way boot contention): not an assertion bug; did not recur.

Iteration 2 sweep: all 8 rounds 86/86. CLEAN.

## Step 7: Run tests and iterate — 2026-08-10T19:30:00.000Z

**Iterations run: 2** (iteration 1: 76/86 × 8 rounds; iteration 2: **86/86 × 8 rounds — clean exit**)

**Tests deleted:** none — every failure traced to a PRD-verbatim rule; all were repairable test-artifact bugs.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_errors.py` — added missing `ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE` + 422 status mapping; PRD §2.6 stage 8 and §3.7 both name this error verbatim, but the enum omitted it (AttributeError killed the test before any request).
- `test_helpers/assertions.py` — added `assert_instant_equal(actual, expected)`: PRD pins the *instant* of `valid_from`/`expiry_date` (§3.5 "set to the activation instant", "365 days after") but never pins their serialization, so string equality was not uniquely derivable; instant comparison keeps the assertion at full strength.

**Fixes applied to `test_suite/`:**
- `test_10_entities_and_envelope.py::test_system_fields_server_minted_on_create` — expected `created_at` corrected to `"2026-05-01T00:00:00.000Z"`; PRD §2.5 verbatim-mandates three fractional digits, so the bare-`Z` expectation contradicted the PRD.
- `test_13_calculations_rbac_occ.py::test_activation_visible_immediately_in_response` and `test_11_state_machine_corners.py::test_registration_expires_via_clock` — `valid_from`/`expiry_date` switched to `assert_instant_equal`.
- `test_01_fee_and_score_variants.py::test_audited_score_includes_aged_filed_at_half_weight` and `test_03_state_machines.py::test_renewal_loop_active_pending_active_with_expiry_extension` — expected expiry corrected from 2028-05-01 to **2028-04-30**: PRD §3.6 says "extends by 365 days from the previous expiry", and 2027-05-01 + 365 days crosses 2028-02-29. The tests had added a calendar year; implementation was correct.
- `test_11_state_machine_corners.py::test_registration_initial_state_draft` — expected provisional fee corrected 7500 → 7800; the default factory cart declares headlights+brake lights (equipment_count=2), so PRD §3.5 gives 7500×1.04=7800. The test's "0-equipment" comment was wrong.
- `test_02_combinatorial_formulas.py::_setup_cf1` — cart A was created with zero equipment, which PRD §3.3 forbids for a GOLF_CART registration (ERR_EQUIPMENT_MINIMUM was the correct response); cart now declares the class minimum (headlights+brake lights), and the floor still binds (7800×0.9=7020 → max(7020, 7500)=7500), preserving the asserted rule.
- `test_08_temporal_overlap.py::test_start_exactly_at_buffer_boundary_legal` → renamed `..._rejected` — PRD §2.10 says a buffered interval that "touches" the new reservation collides (deliberate contrast with half-open route passes, where touching is legal); starting exactly at the 15-minute buffer boundary is therefore a 409 ERR_CHARGING_OVERLAP. The test had asserted the opposite of its own quoted PRD sentence.

**Fixes applied to `implementation/`:** none — the implementation was PRD-correct on every tripped assertion.

**Note on the one infrastructure failure:** iteration 1 had `test_05::test_buffer_violation_returns_charging_overlap` error out in all 8 rounds with "server could not be restarted" (the pytest plugin's hardcoded 15s restart-poll window under 8-way boot contention). No assertion was involved; it did not recur in iteration 2 and no change was made for it.

Orchestrator verification: all 8 `results.{1..8}.json` files present on disk; every round reports passed=86, total=86, failed=0.

## Step 8: Finalize PRD — 2026-08-10T19:40:00.000Z

PRD_FINALIZED.md is complete at `workspace/PRD_FINALIZED.md`.

### Summary

**Line counts:** PRD.md = 335 lines; PRD_FINALIZED.md = 338 lines (+3 lines, +0.9%).

As the diff note predicted, Step 7 applied zero implementation fixes — every tripped assertion traced to a PRD-verbatim rule the implementation already followed (365-day `timedelta` at `registrations.py:158`/`:245`, 0.02 provisional equipment rate at `calc.py:16`, 15-minute touch-collides buffer at `charging.py:18`/`:142`, GOLF_CART equipment minimum, three-fractional-digit `created_at`). Only two edits survived scrutiny; the rest were pure test-fixture bugs requiring no PRD change.

**Changes (one bullet each):**
- §2.5 — insert — added a paragraph pinning the serialization of every server-emitted datetime-valued field (`valid_from`, `expiry_date`, `scheduled_at`, `start_at`/`end_at`, `shift_start`/`shift_end`/`returned_at`, `occurred_at`, `current_utc`, `created_at`, `updated_at`) to ISO 8601 UTC with exactly three fractional digits and trailing `Z`; explicitly excludes date-valued fields (`birth_date`, insurance `effective_date`/`expiry_date`) — `implementation/db.py:28-36` (`format_ts`), `implementation/services/serializers.py:87-88,97,146-147,171-172,195-198,212`, `implementation/routes/clock.py:22`, `implementation/response.py:17`.
- §5 — insert — added the missing catalogue row `ERR_REGISTRATION_NOT_ACTIVE | 422 Unprocessable Entity` (PRD §2.6 stage 8 and §3.7 already named it verbatim with 422, but the §5 table omitted it — the gap that broke the test_helpers enum) — `implementation/routes/routes_passes.py:130`.

**Per-edit pre-edit search log:**

*Edit 1 (§2.5 datetime serialization):*
- (a) Subject: serialization format of server-emitted datetime-valued fields.
- (b) Paths enumerated and read: `db.py:28-36` (`format_ts` — the sole formatter, 3-digit ms + `Z`), `db.py:24-25` (`iso_now`, feeds `created_at`/`updated_at` via `serializers.py:9-11` and `touch` at `db.py:86-89`), `response.py:17` (`api_request_timestamp`), `clock.py:22` (`current_utc`), every serializer in `serializers.py` (registration 87-88, inspection 97, route pass 146-147, charging reservation 171-172, fleet dispatch 195-198, violation 212), plus the non-conforming fields: insurance `effective_date`/`expiry_date` (`serializers.py:121-122`, date-only `YYYY-MM-DD`; stored via `require_date` at `insurance.py:26-27,51-52`) and `birth_date` (`serializers.py:43`, echoed date string). A repo-wide grep for `isoformat|strftime|datetime` formatting across all route files confirmed no alternative serialization exists.
- (c) Wording adjustment: the enumerated list names fields explicitly and scopes registration's `expiry_date` as "a registration's" to disambiguate from the insurance policy's date-valued `expiry_date`; a closing sentence explicitly excludes date-valued fields so the insurance and birth_date paths are not mis-described.

*Edit 2 (§5 catalogue row):*
- (a) Subject: `ERR_REGISTRATION_NOT_ACTIVE` error ID and HTTP status.
- (b) Paths enumerated: PRD §2.6 stage 8 (line 106, names it at 422), PRD §3.7 (line 212, "HTTP 422"), sole raise site `routes_passes.py:130` (422) — confirmed by grep across `routes/` and `services/` that no other endpoint raises it; `errors.py` has no helper for it (raised inline via `ApiError`).
- (c) No wording adjustment needed; the row (ID → 422) is consistent with all enumerated paths. Inserted after `ERR_HOLDER_BARRED` to match §2.6 stage 8 ordering.

No other Step 7 item warranted an edit: the leap-year expiry, 7800 provisional fee, GOLF_CART equipment minimum, buffer-boundary rejection, three-fractional-digit `created_at`, and the 422 `ERR_REGISTRATION_NOT_ACTIVE` semantics are all already pinned verbatim by the existing PRD text and match the implementation exactly.

## Step 9: Complete PRD — 2026-08-10T19:50:00.000Z

All changes verified against the implementation. Final summary:

### Summary

**File produced:** `workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md = 338 lines / 52,729 chars → PRD_COMPLETED.md = 340 lines / 54,652 chars (**+2 lines, +1,923 chars**).

**Counts:** 16 ambiguity-pins, 2 mismatch-revisions (18 change bullets; one edit mixes both kinds).

**Changes (one bullet each):**

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_VALIDATION` (400) — implementation/services/validate.py:118-139
- §2.3 — insert — ambiguity — list sort ties on `created_at` broken by `id` — implementation/services/validate.py:142-143
- §2.3 — insert — ambiguity — `has_more` = `offset + len(items) < total_count` — implementation/response.py:34
- §2.3 — insert — ambiguity — PermitHolder-role listings of holder-owned families implicitly restricted to own resources — implementation/routes/vehicles.py:72-73, registrations.py:113-114, inspections.py:71-73, insurance.py:82-83, routes_passes.py:173-174, charging.py:192-193, fleet.py:175-176
- §2.4 — insert — ambiguity — clock is set unconditionally to `to_iso8601` (may move backward) — implementation/routes/clock.py:20
- §2.4 — revise — mismatch — clock endpoint authenticates/authorizes before body validation, exempting it from the §2.6 pipeline order — implementation/routes/clock.py:15-19
- §2.8 — insert — ambiguity — `total_score` and renewal scores serialize as JSON numbers — implementation/services/serializers.py:14-19
- §3.1 — revise — mismatch — `fleet_program_enabled` only gates the provisional fleet-discount assumption; it does not gate the fleet endpoints — implementation/routes/fleet.py:23-44,110-149; services/calc.py:82-84
- §3.1 — insert — ambiguity — community update may also update the display `name` — implementation/routes/communities.py:62-63,96-97
- §3.2 — insert — ambiguity — deposit `amount_cents` must be a positive integer (≥ 1) — implementation/routes/permit_holders.py:157
- §3.3 — insert — ambiguity — retirement blocked by a live registration rejected with `ERR_INVALID_STATE` (409) — implementation/routes/vehicles.py:91-93
- §3.3 — insert — ambiguity — registration-create `holder_id`/vehicle-owner mismatch rejected with `ERR_NOT_FOUND` (404) — implementation/routes/registrations.py:49-51
- §3.4 — insert — ambiguity — the eight inspection component scores are null until finalization — implementation/routes/inspections.py:43-44
- §3.5 — insert — ambiguity — "most recently finalized inspection" means finalization order, not `scheduled_at` — implementation/services/engine.py:57-65; routes/inspections.py:101-102
- §3.5 — insert — ambiguity — FINALIZED-variant 365-day fleet-usage window is inclusive on both bounds — implementation/services/calc.py:89-99
- §3.6 — insert — ambiguity — a late (EXPIRED) renewal also records `renewal_score_provisional` at the renew instant — implementation/routes/registrations.py:205-206
- §3.6 — insert — ambiguity — renewal-score recency boundaries inclusive (exactly 180d → full, exactly 365d → half) — implementation/services/calc.py:181-184
- §3.7 — insert — ambiguity — route-pass `holder_id`/registration-holder mismatch rejected with `ERR_NOT_FOUND` (404) — implementation/routes/routes_passes.py:112-113
- §3.8 — insert — ambiguity — out-of-range `slot_index` rejected with `ERR_VALIDATION` (400) — implementation/routes/charging.py:130-133
- §3.8 — insert — ambiguity — checkout before `shift_start` rejected with `ERR_INVALID_STATE` (409) — implementation/routes/fleet.py:192-193
- §5 — insert — ambiguity — undefined paths and unsupported methods yield `ERR_NOT_FOUND` (404) — implementation/app.py:39-47

Everything else in the implementation (all endpoints, envelope shape, state machines, fee/late-fee/score formulas, interval semantics, cascades, OCC guards, error catalog, pipeline stage order) was already uniquely pinned by PRD_FINALIZED.md and required no change.
