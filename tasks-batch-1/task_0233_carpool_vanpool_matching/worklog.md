# Worklog — task_0233_carpool_vanpool_matching

## Step 1: Create task directory — 2026-06-07T16:40:20.000Z

Created `tasks/task_0233_carpool_vanpool_matching/` and `tasks/task_0233_carpool_vanpool_matching/workspace/` via `mkdir -p`. Directory ID pre-allocated (0233); no ./tasks/ scan performed. Task designed at Expert difficulty (§0.4).

## Step 2: Generate scaffold — 2026-06-07T17:03:06.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` with a clean verdict. I generated the scaffold purely from the scenario description and the skill specification, without consulting any sibling task.

**Task:** `task_0233_carpool_vanpool_matching` — Carpool & Vanpool Matching, generated at **§0.4 Expert** tier.

**Files written** (all under `tasks/task_0233_carpool_vanpool_matching/`):
- `SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile:** primary archetype quota_allocation, secondary pricing_engine; flat topology; parallel state-machine shape; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation.

**Scale (Expert band):**
- **Entities:** 11 — EmployerProgram, Member, Vehicle, Pool, MatchRequest, Membership, Trip, Reservation, GuaranteedRideHome, SubsidyLedgerEntry, ReliabilityEvent (last two append-only, `common_fields: false`).
- **State machines:** 6 — EmployerProgram (ACTIVE↔FROZEN), Pool (cyclic SUSPENDED↔ACTIVE), MatchRequest (cyclic MATCHED→OPEN revert), Trip (linear w/ heavy cascades), Reservation (parallel `reservation_status` × `payment_status`), GuaranteedRideHome (branching APPROVE/DENY fork).
- **Calculations:** 6 — trip_total_cost, cost_share (ESTIMATE vs FINAL dual-variant, tiered occupancy mode-a), subsidy (per-layer rounding mode-b + monthly-cap waterfall), reliability_score (weighted, CONFIRMED vs PROVISIONAL dual-variant), grh_reimbursement (waterfall), match_score (weighted selector w/ pinned tie-break on created_at).
- **Endpoints:** 56 (incl. 2 test-driving `/_clock/set`, `/_batch/run`, and single+filtered-list GETs for FK reverse-reachability).
- **Errors:** 20.
- **Roles:** 4 — PlatformOps (opaque override), ProgramAdmin (opaque), Driver (entity_backed:Member), Rider (entity_backed:Member).
- **Concurrency:** 2 OCC rules (reservation-create-stale-trip on Trip.version; membership-join-stale-pool on Pool.version), both 412.

**Design indices:**
- **§1.8 (depth):** 18 instances = 9 Difficulty Rules × 2 each.
- **§1.9 (breadth):** 40 instances total — 35 active + 5 `excluded_because` stubs (each citing a real §1.8 instance), spanning all 9 claim-extraction sections.

**Verification performed:** all formula-derived asserts pre-computed as literals via Python (cost-share est/final divergence 1600 vs 3200, subsidy per-layer 1001 vs naive 1249, reliability 70.0/55.0/85.0/87.0 boundaries, GRH caps, match scores 60.00/57.00). Confirmed: zero unbound `${var}` placeholders; OCC fields are `${var}` with version captures threaded via `GET /pools/{id}` re-reads where a second mutation was needed; no forbidden concurrency vocabulary; unique instance names across §1.8∪§1.9; all `grounds` refs resolve to declared §1.1–§1.7 elements; enum closure (FROZEN now has a producing transition). `scaffold_lint.py` → **VERDICT: clean lint** (56 endpoints, 11 entities, 498 calls scanned, 0 violations).

## Step 3: Copy shared files — 2026-06-07T17:03:37.000Z

Copied root `INSTRUCTION.md` → `tasks/task_0233_carpool_vanpool_matching/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T17:09:09.000Z

**Output:** `workspace/PRD.md` (278 lines, 47270 bytes). Generated from SCAFFOLD.yaml only; both design indices withheld.

### Section structure
- **§1 Introduction** — 3 paragraphs, business incentive then technical lens (seat-allocation + pricing engine under financial controls).
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties & Versioning, 2.5 Reconciliation/Cascades/Derived Fields, 2.6 OCC, 2.7 Money/Precision/Rounding, 2.8 Validation Order & Pipeline, 2.9 Nested Path Validation, 2.10 Simulation Clock & Periodic Batch.
- **§3 Business Logic** — 10 subsections: 3.1 Employer Programs/Subsidy Budget, 3.2 Members/Vehicles/Wallets, 3.3 Pool formation & joining, 3.4 Matching, 3.5 Trip scheduling & cancellation cascade, 3.6 Reservation/check-in/no-show, 3.7 Cost-share & subsidy arithmetic, 3.8 Reliability scoring, 3.9 GRH, 3.10 Subsidy ledger.
- **§4** — 57-row endpoint table. **§5** — 20-error catalogue.

### Coverage
- **Entities:** 11 (incl. 2 append-only audit records SubsidyLedgerEntry/ReliabilityEvent, no updated_at/version, called out in §2.4).
- **Endpoints:** 57.
- **Calculations:** 6 — trip_total_cost, cost_share (ESTIMATE/FINAL), subsidy (forward/final waterfall, per-layer rounding mode-b), reliability_score (CONFIRMED/PROVISIONAL), grh_reimbursement, match_score — pinned evaluation/rounding order; constants embedded (tier factors 0.80/0.90/1.00, reliability weights +2.0/−15.0/−6.0/−4.0, match weights 10/1/0.05, buffer 15 min, expiry 14 days, GRH default 4).
- **Errors:** all 20, incl. two catalog-only codes (ERR_PROGRAM_BUDGET_EXHAUSTED, ERR_VALIDATION_DRIVER_REQUIRED) given narrative triggers.

### Hard Contracts — all PASS
- Contract 1 (Field-Name Coverage): entities 69/69, endpoint inputs 52/52, 0 missing.
- Contract 2 (Rule Coverage): validation priority ordering; both OCC rules express write endpoint + expected_*_version + error_id + 412; all 6 calcs/transitions/cascades/applies_to covered.
- Contract 3 (§3 Path Purity): 465 §3 backtick tokens, 0 slash-leading, 0 bare HTTP-method, 0 method+path combined.
- §2.2 verbatim block byte-for-byte; all 21 state values + enum values present.

### Notable information-scattering choices
- Reservation inputs split across §3.6 (core + OCC) and §3.7 (cost-share/subsidy params); business guards interleaved in §3.6.
- Dual-variant cost-share/subsidy in §3.7; consumers (trip completion, reservation estimate) in §3.5/§3.6 — estimate-vs-final divergence must be stitched.
- 3-level cascade chain (pool suspend/close §3.3 → trip-cancel §3.5 → reservation refund/ledger-credit) spread across three subsections.
- Constants given as word/unit conversions ("fifteen minutes", "fourteen days", "five hundredths times").

## Step 5: Generate unit tests — 2026-06-07T17:27:09.000Z

**Task:** task_0233_carpool_vanpool_matching (Expert tier) — complete test infrastructure from the two design indices, PRD.md as adjudicating contract.

### test_helpers/ (Stage 1) — 9 files
- `types.py` — role enum, 11 status enums, entity TypedDicts. SubsidyLedgerEntry/ReliabilityEvent append-only (id+created_at only, no updated_at/version).
- `api_client.py` — one method per endpoint (all 50+ incl. /_clock/set, /_batch/run, /healthz).
- `api_errors.py` — 20 error IDs with §5 status map (ERR_INVALID_REQUEST/ERR_NO_MATCH_FOUND/ERR_VALIDATION_DRIVER_REQUIRED → 422; OCC → 412; wallet → 402).
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Driver/Rider entity_backed:Member with make_*_headers(member_id); ProgramAdmin/PlatformOps opaque), `fixtures.py` (setup_active_pool, setup_completed_single_rider_trip, setup_rider_with_reliability via no-show accumulation, GRH chains), `__init__.py`.

### test_suite/ (Stage 2) — conftest + 11 files, 69 tests
All 69 docstrings carry exactly one `Design:` tag; all 73 PRD citation quotes verified verbatim; zero skip/xfail; zero scaffold/§ leakage.

### Coverage vs design indices
- **Queue A (Difficulty):** 18 instances. **17 translated** (≥2 independent tests each — primary in 01–10, corroboration in test_11). **1 SKIPPED:** `cross_entity_state_dependency/reserve_requires_pool_active_pair_reservation_pool` — fails unique-derivability (recipe asserts ERR_INVALID_STATE but PRD §2.5+§2.8 uniquely derive ERR_STALE_TRIP_VERSION on the stale trip_v0 replay). Gap left as gap; no freelance backfill.
- **Queue B (Corner):** 40 instances. **35 non-stub all translated (≥1 test each).** 5 excluded_because stubs correctly NOT translated; all 5 difficulty_instance cross-refs resolve to real §1.8 names.

### Notable adjudication calls
- rider_double_booked / safety_beats_constraint: scaffold comments cite 30-min buffer / different ordering, but cited+asserted per PRD prose (15-min buffer §3.6; reliability-before-seats §2.8).
- Hand-verified arithmetic vs PRD: subsidy 2080, per-layer rounding 1001/net 504, occupancy tiers 1000 (N=4)/1500 (N=3), reliability 85.0/70.0/55.0/94.0, match score 60.00.

## Step 6: Generate implementation — 2026-06-07T17:27:09.000Z

### File layout (workspace/implementation/)
- `start.sh` — foreground bash launcher; reads $PORT (default 10000), binds 0.0.0.0, guards pip install on cheap `import flask` check, then `exec python3 app.py`.
- `requirements.txt` — flask==3.0.3.
- `app.py` — Flask entry + all 57 route handlers, error/envelope plumbing, state machines, cascades. Binds 0.0.0.0:$PORT, threaded=True.
- `core.py` — auth/RBAC/ownership, common-field stamping + versioning, derived-field recompute, clock helpers, ledger/event append, pagination, body validators.
- `calc.py` — pure calculation engine (Decimal, round-half-up).
- `db.py` — in-memory Store (dicts keyed by id) + simulation clock + match-request exclusion sets. Wiped on every boot; no seeding.
- `errors.py`/`response.py` — 20-code catalogue + ApiError; success/error envelope (meta/response_type/data, req_ ids, 3-fractional-digit ISO timestamps).

### Endpoints — all 57 from PRD §4
Full CRUD + state transitions for all 9 mutable entities; read-only ReliabilityEvent & SubsidyLedgerEntry; /_clock/set, /_batch/run, /healthz. Filtered lists + offset pagination (limit 1–100 default 10, offset default 0, total_count/has_more in meta), sorted created_at asc.

### Calc/state modules (verified to design literals)
- trip_total_cost (per-mile product rounded before base → 3500/3200/1505)
- cost_share ESTIMATE-vs-FINAL, tiered occupancy 0.80/0.90/1.00, round-once-after-seat-multiply (1600 est → 3200 final on no-show; N=4→1000, N=3→1500)
- subsidy per-layer rounding mode-b + monthly-cap waterfall + frozen/budget guard (1001 vs naive 1249; 2080; cap-to-1200)
- reliability_score CONFIRMED vs PROVISIONAL, weights +2/−15/−6/−4, clamp-then-round-1dp (85.0/70.0/94.0/96.0; provisional 72.0/87.0)
- grh_reimbursement min(claimed, per-event, annual-remaining) (6000)
- match_score 10·days + 1·room + 0.05·driver-reliability, tie-break reliability→created_at never id (60.00/57.00, A→B→A revert via exclusion set)
- State machines: Program ACTIVE↔FROZEN; Pool cyclic w/ suspend/close cascades; MatchRequest cyclic; Trip linear w/ depart-no-show & complete-settlement cascades; Reservation parallel reservation_status×payment_status; GRH branching. OCC on Trip.version/Pool.version (412). Validation precedence 1–15 verified.

### PRD ambiguities resolved
1. Rider double-booking buffer: PRD §3.6 "fifteen minutes" (corner-design said 30); PRD wins → 15 min.
2. Cross-entity reserve gate reads Pool (not Trip) state: SCHEDULED trip whose pool is SUSPENDED → ERR_DEPENDENCY_NOT_READY. Suspend cancels only future SCHEDULED trips (departure_at > clock); past-dated trip stays SCHEDULED, exposes pool gate.
3. Month/year derived counters re-bucketed against simulation clock on read + each GRH/subsidy op; clock rollover resets per §2.10.
4. subsidy_consumed_cents always recomputed as signed ledger sum (single source of truth), never incremented in place.

### Boot verified
Killed + relaunched via start.sh twice on same port; store empty each boot; health responds within seconds; 8 ad-hoc end-to-end suites pass.

## Step 7: Run tests and iterate — 2026-06-07T19:45:57.790Z

All confirmed. Every one of the 69 tests has status `passed` in all 8 parallel rounds, no skipped/xfail markers exist, and the run is stable across the full concurrent sweep.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep).

**Result:** Clean. All 8 concurrent rounds reported `passed == total == 69`, with `failed=0`, `errors=0`, `skipped=0`. No flakiness surfaced — the union of failing tests across all rounds is empty.

**Tests deleted:** None. No test exhibited PRD-silence or unique-derivability collapse, because no test failed in any round.

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

The implementation at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0233_carpool_vanpool_matching/workspace/implementation/` already passes the full suite stably under `--isolation per-test-server` across 8 concurrent rounds. Per-round wall time is ~60s; the concurrent sweep finished well within budget.

Note: My very first attempt to summarize the results read a nonexistent `outcome` field (the runner uses `status`), which made every test spuriously appear to "fail." Re-reading with the correct `status` field confirmed a clean 69/69 pass in every round. No exit-condition ambiguity remains — the contract (all 8 rounds `passed == total`) is satisfied.

## Step 8: Finalize PRD — 2026-06-07T19:46:36.249Z

**SKIPPED** per the Step 8 skip condition. Step 7 exited on the first 8-round parallel sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — i.e. zero iterations beyond the baseline. `PRD.md` already uniquely determined every behavior the implementation exhibits at the Step 7 fix sites (there were none), so no `PRD_FINALIZED.md` is produced. Step 9 takes `workspace/PRD.md` as its source per its input rule (PRD_FINALIZED.md absent).

## Step 9: Complete PRD — 2026-06-07T19:52:56.830Z

All edits complete. Here is my summary.

## Summary

Produced `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0233_carpool_vanpool_matching/workspace/PRD_COMPLETED.md` as a minimal patch over `workspace/PRD.md` (no `PRD_FINALIZED.md` existed, so I started from `PRD.md` per the rule).

**Line counts / char-delta**
- Source `PRD.md`: 278 lines, 47,270 chars
- `PRD_COMPLETED.md`: 278 lines, 49,079 chars
- Char delta: **+1,809**; line delta: **0** (all changes are in-paragraph inserts/revisions; no new paragraphs or sections)

**Counts:** 6 ambiguity-pins, 1 mismatch-revision (across 6 edited paragraphs).

**Changes**
- **§3.1 (Employer Programs) — insert — ambiguity** — pinned that `monthly_benefit_cap_cents`, `grh_annual_cap_cents`, `grh_per_event_cap_cents`, `subsidy_budget_cents` are required integers ≥ 0, `employer_name` must be a string, and `grh_max_events_per_year` is a non-negative integer — `app.py:124-135`.
- **§3.2 (Members) — insert — ambiguity** — pinned the previously-silent derivations of the three time-bucketed counters: `month_benefit_used_cents` = signed sum of this member's `RESERVATION_FINALIZED`/`RESERVATION_CANCELLED` ledger amounts in the current clock month (floored at 0); `grh_year_used_cents`/`grh_year_event_count` = sum/count of `GRH_REIMBURSED` ledger entries in the current clock year; re-derived against the clock on read/adjudication; plus `amount_cents` may be positive or negative and registration-time `wallet_balance_cents` ≥ 0 — `core.py:248-279`, `app.py:203-204,259`.
- **§3.3 (Pools) — insert — ambiguity** — pinned `departure_days` elements are the seven weekday codes and `base_cost_cents`/`per_mile_cents` are required integers ≥ 0 — `app.py:328-332`.
- **§3.4 (Match requests) — insert — ambiguity** — pinned `needed_days` elements are the seven weekday codes and the departure-min bounds are required integers — `app.py:483-492`.
- **§3.7 (Trip completion) — insert — ambiguity** — pinned that the rider wallet is debited by `net_charge_cents` and floored at 0, with no insufficient-funds error at completion — `app.py:868`.
- **§3.7 (Trip completion) — revise — mismatch** — PRD said a `RESERVATION_FINALIZED` debit "is appended" for each finalized reservation unconditionally; impl appends (and recomputes consumed/month-benefit) only when `final_subsidy_cents > 0`, appending nothing for a zero subsidy. Revised to match — `app.py:872-876`.
- **§3.9 (GRH claims) — insert — ambiguity** — pinned `claimed_fare_cents` is a required integer ≥ 0, an optional `trip_id` must resolve to an existing trip, and `denial_reason` is unset at creation — `app.py:1160-1173`.

**Notes (verified, no change needed):** `ERR_PROGRAM_BUDGET_EXHAUSTED` is in the §5 catalogue but never raised by impl (budget overrun "collapses to 0" per §3.7, which the PRD already states) — the catalogue listing is not a behavioral claim, so no edit. GRH reimburse appends its `GRH_REIMBURSED` debit unconditionally (no `>0` guard), an intentional asymmetry vs. the finalization path, which the PRD §3.9 already states unconditionally — left intact.
