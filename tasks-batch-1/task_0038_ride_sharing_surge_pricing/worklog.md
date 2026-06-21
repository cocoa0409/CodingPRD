# Worklog — task_0038_ride_sharing_surge_pricing

## Step 1: Create task directory — 2026-05-29T02:05:25Z

Created `tasks/task_0038_ride_sharing_surge_pricing/` and `tasks/task_0038_ride_sharing_surge_pricing/workspace/`.

## Step 2: Generate scaffold — 2026-05-29T02:20:35Z

All three files are valid, the file split is honored, and the lint is clean. The scaffold is complete.

## Summary

Generated the three scaffold artifacts for **task_0038_ride_sharing_surge_pricing** under the given directory. All pass `scaffold_lint.py` with `VERDICT: clean lint` (283 calls scanned across §1.8/§1.9; all §1.1 FKs reverse-reachable).

**Complexity profile:** Pricing engine (primary) + Quota/allocation (secondary); flat topology; branching state machines; peer_roles; immediate consistency. Expert-leaning band.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **8 entities:** Zone, Driver, Rider, SurgeSnapshot (append-only, `common_fields:false`), Trip, AirportQueueEntry, Quest, Dispute.
- **5 state machines:** Driver (OFFLINE/AVAILABLE/ON_TRIP), Trip (branching REQUESTED→{MATCHED,EXPIRED}, MATCHED→{ENROUTE→COMPLETED, CANCELLED}), Quest (ACTIVE→{EARNED,EXPIRED}), Dispute (OPEN→{UPHELD,REJECTED}), AirportQueueEntry (WAITING→{DISPATCHED,WITHDRAWN}) — with multi-hop cascades (trip-complete → driver relocate → dropoff-zone supply; go-offline → queue withdraw → re-sequence).
- **1 concurrency rule:** OCC on `Zone.version` for surge-snapshot publish (`ERR_STALE_ZONE_VERSION`, 412).
- **5 calculations:** `surge_multiplier` (ratio band + rush step + cap), `heat_level` (Heat Map bucketing), `trip_final_fare` (surge-then-fee, pinned rounding order), `driver_payout` (80% of surged fare excl. booking fee), `dispute_refund` (bounded by remaining net paid).
- **16 validations** (ordered, incl. two temporal-overlap rules with contrasting interval semantics), **37 endpoints** (CRUD + actions + FK reverse-reachability GETs + `/_dispatch/tick` test-driving endpoint), **16 error codes**, **3 roles** (Dispatcher opaque; Rider/Driver entity-backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 Difficulty Rules × 2 = **18 instances**, each with computed-literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 8 sections, **34 active instances + 3 `excluded_because` stubs** (covering CRUD/defaults/computed fields, invalid transitions, terminal lockdown, validation errors, RBAC denials, FK filtered lists, OCC stale/fresh, pagination envelope, immediate-consistency).

Note: `api_prefix` is `/` (flat domain — all collections are top-level).

## Step 3: Copy shared files — 2026-05-29T02:20:52Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-29T02:24:20Z

Generated `workspace/PRD.md` — a prose PRD for the Ride-Sharing Dynamic Surge Pricing API (~250 lines).

**Sections:** §1 Introduction; §2 Global Specifications (10 subsections: RBAC, response envelope, pagination, common resource properties incl. SurgeSnapshot common_fields:false exception, hierarchical consistency/floor-0 counters, nested-resource existence, precision/rounding, surge+Heat Map overview, OCC on surge publish, validation ordering); §3 Business Logic (11 subsections: zone/onboarding, driver availability, trip request+quote freezing, dispatch matching non-airport vs FIFO airport, trip lifecycle with cascades, surge snapshot publishing 4-step algorithm + half-open window + heat bands, final-fare calc, driver-payout calc, quests closed-interval overlap, airport queues, disputes/refunds); §4 37-endpoint table; §5 16-error table.

**Hard contracts all PASS:** Contract 1 (48 field/param names, 0 missing); Contract 2 (all transitions, 5 calculations, validation conditions+priority, OCC rule all expressed); Contract 3 (§3 path purity, 0 violations). All 16 error IDs, 3 role names, enumerated states appear verbatim; §2.2 envelope byte-for-byte.

## Step 5: Generate unit tests — 2026-05-29T02:35:18Z

Generated complete test infrastructure for task_0038_ride_sharing_surge_pricing.

**Stage 1 — `test_helpers/`** (9 files): types.py (8 entity TypedDicts + 7 enums; SurgeSnapshot omits updated_at/version as common_fields:false), api_client.py, api_errors.py (16 error IDs + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (opaque Dispatcher shared constant + per-instance make_rider_headers/make_driver_headers builders, anonymous_headers for 401), fixtures.py (composite lifecycle: setup_matched_trip → setup_enroute_trip → setup_completed_trip, airport-queue, dispute helpers), __init__.py barrel export.

**Stage 2 — `test_suite/`**: conftest.py + 6 test files, **70 test functions total**, all collecting cleanly.
- Queue A (Difficulty): 36 tests — every 18 difficulty instances covered by exactly 2 tests.
- Queue B (Corner): 34 tests — all 34 non-stub corner instances covered by ≥1 test.

**Skips/exclusions:** 3 excluded_because corner stubs not translated (cross-refs resolve to owning queue-A instances). For difficulty instance trip_not_completed_beats_invalid_refund_amount_on_dispute: PRD §3.11/§2.10 don't pin relative order of COMPLETED-precondition vs refund-amount check, so primary test uses validate_error_is_one_of([ERR_TRIP_NOT_COMPLETED, ERR_INVALID_REFUND_AMOUNT]); second test isolates COMPLETED precondition deterministically. Companion invalid_state_beats_insufficient_wallet IS stated in §2.10 and asserted hard.

**Verification:** all files compile; every difficulty instance has 2 tests, every non-stub corner has 1; PRD citations verified via literal grep; no skip/skipif/xfail; no scaffold leakage.

## Step 6: Generate implementation — 2026-05-29T02:35:18Z

Built complete Python + Flask implementation at workspace/implementation/.

**Files:** start.sh (sentinel-guarded dep install, frees stale $PORT listener, exec python3 app.py on 0.0.0.0:$PORT default 10000), requirements.txt (Flask 3.0.3), response.py (envelope helpers), errors.py (16 error codes + HTTP statuses), db.py (in-memory, empty on boot, UUID ids, common_fields, touch() version bump, monotonic _seq), calculations.py (5 calcs via Decimal/ROUND_HALF_UP), app.py (all 38 endpoints, auth/RBAC, validation ordering, state machines, serializers).

**Key calcs/SMs:** surge_multiplier (ratio bands lower-inclusive → +0.50 rush → clamp 2.50 cap, capped flag); heat_level (COOL/WARM/HOT/BLAZING lower-inclusive upper-exclusive at 1.25/1.75/2.50); trip_final_fare (round(base×mult)+150 booking fee); driver_payout (round(surged×0.80), excl booking fee); dispute_refund (min(requested, final_fare−refunded) floored 0). SMs: Driver OFFLINE↔AVAILABLE↔ON_TRIP; Trip REQUESTED→{MATCHED,EXPIRED}, MATCHED→{ENROUTE→COMPLETED,CANCELLED} with counter cascades; Quest ACTIVE→{EARNED,EXPIRED}; Dispute OPEN→{UPHELD,REJECTED}; AirportQueueEntry WAITING→{DISPATCHED,WITHDRAWN} with FIFO re-sequencing.

**Decisions:** validation ordering per PRD §2.10 (401→403 role→404 left-to-right→403 owner→409 state→business); OCC vs window-overlap order on publish (window-overlap priority 65 before OCC priority 13); multipliers/ratios as floats 2dp; counters floored 0; airport dispatch picks FIFO-earliest WAITING with AVAILABLE driver, re-sequences. Smoke-tested end-to-end.

## Step 7: Test and iterate — 2026-05-29T02:50:00Z

All 8 parallel rounds pass cleanly (69/69 each). Exiting.

**Iterations run:** 2 (initial sweep + verification sweep after fix).

**Tests deleted (1):**
- `test_start_trip_from_requested_returns_invalid_state` (in `test_suite/test_02_trip_lifecycle.py`) — **ERROR PRECEDENCE SILENCE / contradiction**. The test set up a `REQUESTED` trip (no dispatch tick run, so `driver_id` is null per PRD §3.143) and had a driver attempt `/trips/{id}/start`, expecting `ERR_INVALID_STATE`. But PRD §2.10 (the authoritative "Validation Ordering" section) explicitly mandates that the ownership check (`ERR_NOT_RESOURCE_OWNER`) is evaluated **before** the state check (`ERR_INVALID_STATE`). On a `REQUESTED` trip the `driver_id` is null, so the acting driver genuinely fails ownership first, yielding `ERR_NOT_RESOURCE_OWNER` — exactly what the implementation returns. §3.155 lists both checks as existing but does not pin their relative order; §2.10 does, and it favors the implementation. A faithful PRD-only reader following §2.10's explicit ordering produces `ERR_NOT_RESOURCE_OWNER`, so the test's expected outcome is not uniquely derivable from the PRD. Scaffold rule that drove generation: `Corner/state_machines/start_trip_from_requested_returns_invalid_state`.

**Fixes applied to test_helpers/:** none.

**Fixes applied to implementation/:** none. The implementation's `start_trip` ownership-before-state ordering (app.py:657–660) is PRD-faithful to §2.10 and was correctly left unchanged.

Final state: all 8 parallel rounds pass 69/69.

## Step 8: Finalize PRD — 2026-05-29T02:52:00Z

Produced `workspace/PRD_FINALIZED.md`. **Line counts:** PRD.md = 266, PRD_FINALIZED.md = 266. **%-delta = 0%** (verbatim copy, no edits).

**Changes:** None. PRD_FINALIZED.md is byte-identical to PRD.md.

**Rationale:** The single step_7 item was the deletion of `test_start_trip_from_requested_returns_invalid_state` — a fixture/contradiction bug, not a PRD silence or mismatch. PRD §2.10 already explicitly mandates ownership-before-state ordering; with a null driver_id on a REQUESTED trip, ownership fails first (ERR_NOT_RESOURCE_OWNER), exactly what impl returns (app.py:657-660). Step 7 applied no impl fix and no test_helpers fix; impl was PRD-faithful. Pre-edit search confirmed start_trip/complete_trip/cancel_trip all apply ownership before state matching §2.10; expire_trip is Dispatcher-only with no ownership check. No PRD edit warranted.

## Step 9: Complete PRD — 2026-05-29T02:57:42Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan.

**Source vs result:** PRD_FINALIZED.md = 266 lines / 36,283 chars; PRD_COMPLETED.md = 266 lines / 40,185 chars (char-delta +3,902; no line-count change — all in-paragraph edits).

**Counts:** 13 changes — 9 ambiguity-pins, 4 mismatch-revisions.

- §2.3 Pagination — insert — ambiguity — limit/offset clamping (limit<1→1,>100→100,offset<0→0), non-integer→ERR_INVALID_REQUEST — app.py:163-184
- §2.3 Pagination — insert — ambiguity — airport-queue listing ordering: WAITING by position asc (created_at tie-break) then non-WAITING by created_at asc — app.py:456-462
- §2.10 Validation Ordering — revise — mismatch — POST body field presence/type/enum/numeric validation runs before body-referenced existence lookups — app.py:606-615, 911-916, 982-991, 1038-1042
- §3.1 Zones — revise — mismatch — grid_code letter-then-digit NOT enforced (only non-empty string); base_fare_cents required int ≥100 — app.py:327-329
- §3.1 Riders (wallet credit) — insert — ambiguity — amount_cents required int ≥0 → ERR_INVALID_REQUEST — app.py:511
- §3.2 Driver Availability — insert — ambiguity — go-online/offline wrong status (or active_trip_id) → ERR_INVALID_STATE; offline re-sequence created_at tie-break — app.py:564-567, 581-594
- §3.3 Requesting a Trip — insert — ambiguity — left-to-right existence (rider→pickup→dropoff) then X-User-ID==rider_id ownership — app.py:610-615
- §3.4 Dispatch Tick — insert — ambiguity — non-existent zone_id → ERR_NOT_FOUND — app.py:813-816
- §3.5 Cancel — insert — ambiguity — cancel clears driver active_trip_id to null, leaves current_zone_id unchanged — app.py:726-727
- §3.6 Surge Snapshot — insert — ambiguity — effective_to at/before effective_from → ERR_INVALID_REQUEST, before overlap/OCC — app.py:381-382
- §3.9 Quests — insert — ambiguity — target_trips<1 / bonus_cents<0 / window_end<window_start → ERR_INVALID_REQUEST (window before overlap) — app.py:912-918
- §3.10 Airport Queues — revise — mismatch — join checks reordered: airport → already-queued → availability — app.py:846-854
- §3.11 Disputes — insert — ambiguity — create order (body→existence→ownership→COMPLETED→refund≥1), resolve order (decision body validation before OPEN-state) — app.py:983-1000, 1038-1047
- §4 Endpoint table — insert — ambiguity — /zones/{id}/trips and /zones/{id}/airport-queue support status filter — app.py:428-430, 453-455

## Pipeline complete — 2026-05-29T02:57:42Z

Final state: all 8 parallel stability-sweep rounds pass 69/69. Task directory complete with SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}, test_helpers/, test_suite/.
