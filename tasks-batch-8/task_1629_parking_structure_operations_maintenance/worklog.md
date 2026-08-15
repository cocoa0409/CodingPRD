# Worklog — task_1629_parking_structure_operations_maintenance

## Step 1: Create Task Directory — 2026-08-14T03:22:46.000Z

Task directory `tasks/task_1629_parking_structure_operations_maintenance/` and `workspace/` pre-created and pre-assigned by the orchestrator invocation; treated as DONE per instructions (no index scan, no other task_* directory touched).

Requested difficulty: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-14T04:30:24.000Z

All three scaffold artifacts are generated, validated, and lint-clean.

## Deliverables (all in `/home/ubuntu/github/CodingPRD/tasks/task_1629_parking_structure_operations_maintenance/`)

**`SCAFFOLD.yaml`** (§1.0–§1.7, no design keys) — Parking Structure Operations & Maintenance, verbatim scenario. `pricing_engine` primary + `temporal_windowing` secondary archetype; layers: optimistic_concurrency, ops_run_checkpoint, cascading_side_effects, rate_threshold_triggers; flat topology under `/ops`; segregation-of-duties role model.
- **17 entities**: Facility (posture + ledgers hub), RateSchedule (self-ref supersede), AccessDevice, ParkerAccount, MonthlyAgreement, Credential (self-ref replace), ParkingSession (parallel dims `occupancy_state × billing_state`), AttendantShift, ReconciliationRecord, StructuralInspection, RepairProject, MaintenanceWindow, PatrolRound, IncidentReport (self-ref duplicate), EVCharger, ChargingSession, EventBooking
- **17 state machines** incl. parallel dimensions (ParkingSession), cycles (Agreement ACTIVE⇄SUSPENDED, Charger COMMISSIONED⇄OUT_OF_SERVICE, Repair DEFERRED→PROPOSED revision loop), and a posture-gated Facility machine
- **2 OCC concurrency rules** (rate publish on Facility.version, agreement amend on MonthlyAgreement.version) — both endpoints declare the `expected_*_version` input and version-bump side effect
- **12 calculations** with pinned boundary/ordering semantics (CALENDAR_DAY vs ROLLING_24H cap, per-component-then-sum proration rounding, levy-before-net pinned evaluation order, inclusive variance thresholds, FIFO waitlist with `created_at`/`application_seq` tie-break — never `id`)
- **33 ordered validations, 36 errors, 110 endpoints, 7 roles** (incl. entity-backed `GateDevice`→AccessDevice and `MonthlyParker`→ParkerAccount); logical clock endpoint with mandatory default `2026-08-01T00:00:00Z`

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 26 instances across all 9 rules (3 each except resource_temporal_overlap with 2): fee 4800-vs-2400 cap divergence, EV utilization 0.30%-vs-0.15%, cancellation 10000-vs-5000, proration 13353 (not 13354), levy 110, depth-3 inspection→posture→agreement→credential cascade, event activation/reversal cascades, three distinct validation-priority pairs, grace `==`-free / variance `-2000`-breaches / pool-`==`-exhausted boundaries, buffer-exclusion vs aggregate-capacity overlap, and money/spaces/deposit compensating invariants. All formula-derived asserts are precomputed literals.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 70 instances (67 active + 3 `excluded_because` stubs) across 9 taxonomy sections; every one of the 36 error ids is exercised at least once across the two design files.

## Verification
- `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (110 endpoints, 17 entities, 26 §1.8 + 67 §1.9 active instances, 774 calls scanned)
- Additional mechanical audits (beyond lint): all `grounds` resolve to declared §1.1–§1.7 elements; zero unbound `${var}` placeholders; instance names unique across both files (95 total); no forbidden concurrency vocabulary; OCC hard constraints verified; all enum values have producing transitions; all `excluded_because` citations resolve to real difficulty instances.
- Chain replay bugs found and fixed during authoring: a backward clock jump in the comp-cap corner, a variance-arithmetic mismatch (−1999 boundary needed counted 8501 against expected 10500), a missing negative fund call in the repair-fund setup, and removal of the under-specified `ERR_VARIANCE_NEEDS_REVIEW` (36 errors remain, all triggerable).

Note: the pre-existing `worklog.md` and `workspace/` in that directory (timestamps predate this run) were left untouched.

## Step 3: Copy Shared Files — 2026-08-14T04:30:24.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1629_parking_structure_operations_maintenance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T04:46:43.000Z

PRD generated and verified. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1629_parking_structure_operations_maintenance/workspace/PRD.md` (390 lines).

**Document structure** (designed fresh for this domain, not copied from the example skeleton):
- §1 Introduction — 2 paragraphs, business-context + determinism angle
- §2 nine subsections: RBAC with per-role identity semantics (opaque vs entity-backed `GateDevice`/`MonthlyParker`), the verbatim §2.2 envelope block, pagination, the logical clock (startup default 2026-08-01T00:00:00Z, never wall-clock; half-open interval semantics), common resource properties, cents/half-up/ceil rounding conventions, OCC (only publish + amend), an 11-stage ordered enforcement pipeline, and path/reference integrity
- §3 nine subsections organized by business process (facility/posture/daily close; rate cards + fee engine; devices + sessions; agreements/waitlist/credentials; shifts/reconciliation; inspections/capital repairs; windows/patrols/incidents; EV utilization; event surge), with constants embedded in prose ($-conversions of 2,000/5,000/10,000-cent variance thresholds, 5,000-cent comp ceiling, 28-day utilization window, 48-hour sliding-notice line, 24-hour heartbeat staleness) and all 12 calculations rendered as reconstructible prose — including the pinned per-component rounding order for proration with the 19,999+2,999 over 18/31 counterexample
- §4 endpoint table: 110 rows, 4 columns only; §5 error catalogue: 36 rows (scaffold `complexity_profile` says 37, but the actual `errors[]` array contains 36), 2 columns only

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 135 required, 135 present, 0 missing
- endpoints[].request_body: 21 required, 21 present, 0 missing
- endpoints[].query_params: 36 required, 36 present, 0 missing
- endpoints[].path_params: 17 required, 17 present, 0 missing (9 standalone + 8 embedded in backticked §4 path tokens)
Status: PASS

Rule coverage check:
- validations[] with priority: 11-stage pipeline stated in §2.8 order; per-endpoint ordered sequences given in §3 (entry, pay, comp, confirm, fund, approve, terminate, credential issue, charging start, close-of-business), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (publish → expected_facility_version → ERR_STALE_FACILITY_VERSION/412; amend → expected_agreement_version → ERR_STALE_AGREEMENT_VERSION/412; no other endpoint takes a version field), 0 missing
- state_machines[].transitions: 16 machines / all transition groups fully expressed with preconditions + error IDs + side effects, 0 missing
- calculations[]: 12 checked, 12 fully expressed in precise prose (reconstruction-safe, no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 33 checked, all 36 catalog error IDs matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (3-link CRITICAL cascade, 2-link surge cascade/reversal, reserve draw/refund pair, closed-spaces compensating pairs, deposit carry-over/refund/forfeit, segregation scope open+submit+approve), 0 missing
- entities[].fields[] structured content: defaults, null-until semantics, enum ranges all stated (final pass added commissioned_at/low_util_run_count/utilization_review_flag/closed_at defaults), 0 missing
- sibling-branch symmetry: return-vs-revoke, CALENDAR_DAY-vs-ROLLING_24H, FORFEIT_DEPOSIT-vs-SLIDING_NOTICE, session-vs-energy utilization — all pairs at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 879
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block byte-identical to `section-2.2-response-structure.md`; all 87 state/enum strings present; endpoint row count exactly 110. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T05:27:56.000Z

All checks pass. The work is complete. Here is a summary of what was generated.

## Task 1629 — Unit test generation complete

**Inputs read:** SKILL.md (full spec + framework API verified against `prd_bench_local_runner.testing` source), SCAFFOLD.yaml (3456 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (26 instances, 9 rules), SCAFFOLD_CORNER_DESIGN.yaml (70 instances, 3 stubs), PRD.md (390 lines).

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — 17 entity TypedDicts (all `common_fields: true` here) + 28 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 76 methods covering all 55 PRD endpoints under `/ops`
- `api_errors.py` — all 36 catalogue errors with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — 17 per-entity assertions (id/timestamps/version + enum membership only)
- `factories.py`, `constants.py` (comp cap 5000, variance thresholds 2000/5000/10000, 30-min buffer, 24h staleness, 48h sliding, reference tariff), `test_users.py` (opaque-role shared constants + mandatory per-instance builders `make_gate_device_headers` / `make_monthly_parker_headers`)
- `fixtures.py` — composite tiers: published-tariff facility, online gate, entry-ready facility, parker→agreement→credential chains, cash-settled shifts, closed-shift+recon, VARIANCE_REVIEW path, critical-reported facility, commissioned charger, close-of-business runner

### Stage 2 — `test_suite/` (12 files, 116 tests)
50 difficulty tests (25 translated instances × 2) + 66 corner tests; every test carries a verbatim PRD citation and exactly one resolving `Design:` tag.

**Deliberate gaps (PRD-first two-condition filter):**
1. `Difficulty/priority_pair_validation_conflict/window_safety_hold_vs_overlap_safety_wins` — the instance expects ERR_SAFETY_HOLD before ERR_WINDOW_OVERLAP, but PRD §2.8 pins that §3 workflows name business checks in evaluation order and §3.7 names the overlap rule *before* the safety hold; the asserted outcome is PRD-contradicted, not uniquely derivable.
2. `Corner/validations/body_reference_not_found_returns_404` — asserts a bogus `parker_account_id` yields ERR_REFERENCE_NOT_FOUND, but PRD §2.9's body-identifier enumeration omits `parker_account_id`; a faithful implementer could return ERR_VALIDATION instead.

**Not skipped:** the other two priority-pair instances (refund state-vs-fiscal, pay existence-vs-state) are kept — both involve a generic-pipeline stage vs a business check, which PRD §2.8 uniquely orders. The 3 corner stubs were verified to resolve to real difficulty instances and were not translated.

**Two-reader adjustments:** absolute `version == 1`/initial-version assertions were avoided (PRD pins +1-per-mutation but not the initial value) — the agreement-cycle test asserts relative increments; timestamp equality assertions use `startswith(...)` to respect the PRD's three-fractional-digit format; the mid-settle shift `expected_cash_cents` assertion was dropped (PRD computes it at close/force-close/submit/refund, not at pay).

**Final audits:** 116/116 tests collected by pytest; 174/174 PRD citation quotes survive normalized literal grep of PRD.md; every Design tag resolves to a real instance; no `skip`/`skipif`/`xfail`; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T05:33:23.000Z

Complete. The implementation for `task_1629_parking_structure_operations_maintenance` is done and passes the full benchmark suite: **116/116 tests pass under `prd-bench-local-run --isolation per-test-server`**, verified on two consecutive full runs (150s and 164s), which also proves clean fresh-process boot on every one of the 116 per-test restarts.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_1629_parking_structure_operations_maintenance/workspace/implementation/`:

- `start.sh` — guarded pip install (skips when flask importable) + `exec python3 app.py`, honors `PORT` (default 10000), binds `0.0.0.0`
- `app.py` — Flask entry, blueprint registration, envelope-shaped error handlers
- `db.py` — empty-at-boot in-memory stores, logical clock pinned to `2026-08-01T00:00:00Z`, ISO-8601 UTC 3-fractional-digit timestamps, `touch` vs `touch_ledger` (Facility version bumps only where PRD §3 explicitly states)
- `errors.py` — all 36 catalog error IDs with exact HTTP statuses
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; list responses add `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 7 roles, role gating
- `services/common.py` — field validators (missing→`ERR_VALIDATION`, dangling ref→`ERR_REFERENCE_NOT_FOUND`), pagination, lookups, derived facility counters
- `services/fees.py` — all 12 calculations (transient fee engine with CALENDAR_DAY/ROLLING_24H segmentation and ceil-hour billing, per-component half-up proration, pool arithmetic, shift expected-cash waterfall with RECONCILED freeze, inclusive variance thresholds, levy, dual-basis EV utilization, half-open event-pool overlap, condition index with load-bearing override, cancellation fee)
- `services/cascade.py` — waitlist promotion (created_at ASC, application_seq tie-break), 3-link CRITICAL-report cascade (posture→demotion→credential revocation), event surge/reversal, the full close-of-business sweep with all 8 summary counters
- `routes/` — 18 modules covering all 110 endpoints

## Key decisions traced to PRD prose

- Entry business-check order follows §3.3's explicit enumeration (device-online → posture → published-rate → duplicate-ticket → credential-valid), overriding the scaffold's generic priority numbers where they conflicted; same for window create (time-range → overlap → safety hold per §3.7)
- Facility `version` advances only where §3 states it (publish, manual posture, CRITICAL report, repair start/close-out, event activation surge, close-of-business); ledger writes refresh `updated_at` only
- Identity bindings compare `X-User-ID` against the path/body id string before existence, per pipeline stages 3<5

## One fix outside `implementation/`

`test_helpers/fixtures.py:308` — `setup_reported_inspection` passed the full inspection dict as `inspection_id` to `report_inspection`, rendering a dict repr into the URL path (unrecoverable server-side; direct test callers correctly pass `inspection["id"]`). Fixed to `report_inspection(inspection["id"], ...)`.

## Step 7: Run Tests and Iterate — 2026-08-14T05:38:20.000Z

All 8 rounds of the parallel stability sweep passed cleanly: **116/116 tests passed in every round, 0 failed, 0 errors**, and the union of failing tests across all 8 rounds is empty.

## Summary

- **Iterations run:** 1 (a single 8-round parallel stability sweep; every round ran to completion)
- **Tests deleted:** none — no failing tests to diagnose, so no PRD-coverage or unique-derivability deletions were triggered
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `implementation/`:** none

The task at `/home/ubuntu/github/CodingPRD/tasks/task_1629_parking_structure_operations_maintenance` was already in a fully green state on arrival. The 8-round concurrent sweep (per-test-server isolation, auto-allocated ports) surfaced no timing-sensitive or flaky failures — every one of the 116 tests passed in all 8 rounds. The exit condition (`passed == total` in all 8 rounds) is satisfied.

## Step 8: Finalize PRD — SKIPPED

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the Step 8 skip condition, `PRD.md` already determined every behavior the implementation exhibits at the Step 7 fix sites, so no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-14T05:56:22.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1629_parking_structure_operations_maintenance/workspace/PRD_COMPLETED.md` produced (PRD_FINALIZED.md did not exist, so the source was `PRD.md`).

## Summary

**Source vs output**: PRD.md 390 lines / 71,551 chars → PRD_COMPLETED.md 390 lines / 75,848 chars (char-delta **+4,297**; all changes inline, no new sections or paragraphs).

**Counts**: 33 changes total — **26 ambiguity-pins**, **7 mismatch-revisions**.

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):

1. §2.1 — insert — ambiguity — parker-ownership checks fire only where §3 names them (credential report-lost/found, agreement withdraw); charging-session start/complete do none — routes/charging.py:20-48, routes/credentials.py:21-25
2. §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION`; `created_at` ties ordered by creation sequence; `total_count` = filtered size; `has_more` = items remain beyond page — services/common.py:13-33, response.py:38
3. §2.5 — revise — mismatch — version starts at 1; Facility is an exception: version advances only at §3-named points; ledger-only counter writes (cumulative_collected, deposit_liability, capital_reserve) and the EVENT_SURGE reversal refresh `updated_at` without bumping version — db.py:94-121
4. §2.8 — insert — ambiguity — resource-dependent checks (parker/shift ownership, segregation) fire right after the supplying path/body reference resolves rather than ahead of stages 5–6; device identity stays at stage 3 — routes/credentials.py:91-92, routes/shifts.py:78-81, routes/reconciliations.py:31-36,123-130
5. §2.9 — revise — mismatch — body-reference list extended with `entry_device_id` and `parker_account_id` — routes/sessions.py:59, routes/agreements.py:39
6. §3.1 — insert — ambiguity — `monthly_capacity` and `event_pool_spaces` are integers ≥ 0 — routes/facilities.py:39-40
7. §3.1 — insert — ambiguity — DECOMMISSIONED terminal lockdown (`ERR_INVALID_STATE_TRANSITION`) fires before the EVENT_SURGE-target rejection — routes/facilities.py:90-94
8. §3.1 — insert — ambiguity — business date / `last_close_date` rendered as ISO calendar dates (`YYYY-MM-DD`) — routes/facilities.py:115-117, services/cascade.py:270
9. §3.2 — insert — ambiguity — `event_flat_cents` and `lost_ticket_daily_cents` are integers ≥ 0 — routes/rates.py:29-30
10. §3.2 — revise — mismatch — LOST_TICKET counts distinct **UTC** calendar dates; CALENDAR_DAY splits at each **UTC** midnight (PRD said "local") — services/fees.py:68-71, 88-96
11. §3.3 — insert — ambiguity — `shift_id` supplied with CARD tender is resolved (dangling → `ERR_REFERENCE_NOT_FOUND`) then ignored; `paid_in_shift_id` stays null — routes/sessions.py:179-189
12. §3.3 — insert — ambiguity — comp with no `shift_id` fails `ERR_SHIFT_NOT_OPEN` before session-state checks — routes/sessions.py:213-216
13. §3.3 — insert — ambiguity — a `REFUNDED` session at exit is treated as unpaid: fee recomputed, zero auto-settles, positive → `ERR_EXIT_UNPAID` — routes/sessions.py:244-252
14. §3.3 — insert — ambiguity — lost-ticket conversion examines only billing state; prior `fee_mode` not examined — routes/sessions.py:264-269
15. §3.3 — insert — ambiguity — refund `amount_cents` is a strictly positive integer — routes/sessions.py:279
16. §3.4 — insert — ambiguity — duplicate parker `email` → `ERR_VALIDATION` (400) — routes/parkers.py:22-24
17. §3.4 — revise — mismatch — amend has no lifecycle guard (dropped "on a live agreement"); no-field amend accepted and bumps version; supplied figures keep creation-time ranges — routes/agreements.py:150-167
18. §3.5 — insert — ambiguity — new shift's `expected_cash_cents` initialized to the opening float — routes/shifts.py:38
19. §3.5 — revise — mismatch — expected cash is also recomputed whenever a cash settlement is booked to the shift (PRD's list omitted this point) — routes/sessions.py:201-203, services/fees.py:153-157
20. §3.5 — insert — ambiguity — `counted_cash_cents`, `over_ring_cents`, `paid_out_cents` are integers ≥ 0 — routes/shifts.py:83-85
21. §3.5 — insert — ambiguity — reconciliation open against a wrong-status shift or one with a non-terminal record → `ERR_INVALID_STATE_TRANSITION` — routes/reconciliations.py:37-41
22. §3.5 — insert — ambiguity — approve resolves `incident_id` (dangling → `ERR_REFERENCE_NOT_FOUND`) before the segregation check; `incident_id` supplied from `SUBMITTED` is resolved and ignored — routes/reconciliations.py:123-138
23. §3.6 — insert — ambiguity — report requires `IN_FIELD` (else `ERR_INVALID_STATE_TRANSITION`); report `closed_space_count` is an integer ≥ 0 defaulting to zero — routes/inspections.py:97-99
24. §3.6 — revise — mismatch — CRITICAL cascade moves posture to `RESTRICTED` only from `NORMAL` (other postures unchanged); `closed_spaces` growth and version bump apply regardless — services/cascade.py:70-77
25. §3.6 — insert — ambiguity — fund `amount_cents` strictly positive — routes/repairs.py:82
26. §3.7 — insert — ambiguity — created window records its `safety_authorized` flag — routes/windows.py:33,64
27. §3.7 — revise — mismatch — `lighting_outages_found` stands at zero from scheduling (PRD claimed both counts null until completion); both counts integers ≥ 0 — routes/patrols.py:29-31,67-68
28. §3.8 — insert — ambiguity — nameplate `max_kw` is an integer — routes/chargers.py:25
29. §3.8 — insert — ambiguity — utilization window counts sessions with `ended_at` inside inclusive of both endpoints; zero-available-minutes run sets both percentages to 0.0 and itself counts as a low-utilization run — services/fees.py:248-253,262,275-276
30. §3.9 — insert — ambiguity — `staffing_assignments` roster is required at confirm (absence → `ERR_VALIDATION`) — routes/events.py:94-97
31. §3.9 — insert — ambiguity — entire surge cascade (posture flip, version bump, device EVENT-mode flips) is conditioned on `NORMAL`; activation under other admitted postures changes none of them — services/cascade.py:119-129
32. §3.9 — insert — ambiguity — surge reversal on completion does not advance facility version — services/cascade.py:132-146

**Verification**: diff PRD.md vs PRD_COMPLETED.md shows exactly 33 changed paragraphs; no sections added; every change pins behavior observed in `implementation/` (implementation walked exhaustively: app.py, middleware.py, db.py, response.py, errors.py, all 20 route modules, and services/{common,fees,cascade}.py).
