# Worklog — task_0876_smart_curb_loading_zone

## Step 1: Create task directory — 2026-07-28T11:44:00.000Z

Folder pre-created by user (tasks/task_0876_smart_curb_loading_zone). Step 1 directory scan/auto-index skipped per instructions. Created workspace/ subdir.

## Step 2: Generate scaffold (Expert) — 2026-07-28T11:50:00.000Z

All three artifacts generated, self-consistent, pass scaffold_lint.py cleanly. Generated purely from scenario + skill spec (no sibling tasks consulted).

Files written: SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 18 instances), SCAFFOLD_CORNER_DESIGN.yaml (§1.9, 22 active + 8 excluded-because stubs).

Scale: 10 entities · 48 endpoints · 6 state machines · 6 calculations · 17 errors · 5 roles · 1 concurrency rule.
Lint: VERDICT clean lint — 355 setup/trigger calls checked; all 16 FKs have reverse-reachability GETs; all grounds resolve.
Archetype/profile: temporal_windowing × pricing_engine; flat topology; cyclic + parallel state machines; segregation_of_duties role model; layers = OCC, cascading side-effects, dual-variant calc, rate/threshold triggers.

Notable design decisions (nine difficulty rules):
- Dual-variant calcs: reservation price ESTIMATE (booked 45min→900) vs SETTLED (observed 62min→1500) on Reservation; citation fine ISSUE (7500) vs UPHELD-late (+25%→9375) on Citation.
- Combinatorial: mode (a) tiered TOU×surge×slots (peak+tier2+3 slots→1350); mode (b) event refund with pinned round-per-reservation-then-sum (33+33=66, not 67).
- Non-linear state machines: CurbPermit cyclic (UNDER_REVIEW→DRAFT revision loop); Reservation parallel booking_status × payment_status axes.
- Transitive cascades: depth-3 event.activate → zone SUSPENDED → reservation CANCELLED_BY_EVENT+REFUNDED → LedgerEntry REFUND; depth-2 permit.revoke → reservation cancel → ledger refund.
- SoD/four-eyes: permit reviewer (CurbPlanner) X-User-ID must differ from approver (PermitApprover) — validated vs recorded reviewer_user_id.
- OCC: zone-redesignate-stale on CurbZone.version via expected_zone_version (412).
- Conservation invariants: per-reservation ledger balance returns to 0; Permittee outstanding_fines_cents restored to pre-issue on citation DISMISSED.
- Temporal overlap two interval semantics: reservation half-open aggregate capacity (adjacency allowed) vs schedule-window closed exclusive + 15-min turnover buffer.
- Boundary precision: surge ratio >= 0.80 → tier2; schedule buffer gap < 15 → conflict.
- Priority-pair conflicts: referential (ERR_PERMIT_NOT_ACTIVE) beats temporal (ERR_ZONE_CAPACITY_CONFLICT); safety/SoD beats referential (ERR_ZONE_NOT_ACTIVE).

Default logical clock pinned at 2026-05-01T00:00:00Z; POST /_clock/set_current_utc and /_sensor/* test-driving endpoints back the sensor-occupancy and time-gated flows.

## Step 3: Copy INSTRUCTION.md — 2026-07-28T11:52:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-28T11:58:00.000Z

Output: workspace/PRD.md — 273 lines. Did not open either withheld design file.
Sections: §1 Introduction; §2 Global Specs (11 subsections: RBAC, Response Structure, Pagination, Common Resource Properties, Referenced-Resource Resolution, Monetary Precision & Basis-Point Arithmetic, OCC on Zone Redesignation, Cascade Consistency, Validation Ordering priority 1–9, Revenue Ledger, Segregation of Duties); §3 Business Logic (8 subsections); §4 Endpoint table (48); §5 Error table (17).
Hard Contract: Field coverage 67/67 PASS; Rule coverage PASS (OCC, SoD, cascades, dual-variant calcs, pinned round-then-sum, 15-min buffer, all constants embedded); Path purity PASS (0 paths/methods in §3 prose).

## Step 5: Generate unit tests — 2026-07-28T12:15:00.000Z

test_helpers/ (9 files): types.py (10 entity TypedDicts, common_fields branching — PricingPolicy/ScheduleWindow/LedgerEntry id+created_at only), api_client.py (50 endpoints), api_errors.py (17 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (entity_backed Permittee make_permittee_headers; four opaque roles), fixtures.py (setup_active_permit, setup_confirmed_reservation, setup_disputed_citation, record_occupancy, ledger inspection), __init__.py.
test_suite/: 9 test files + conftest, 59 tests total. Queue A (Difficulty): 36 tests (all 18 instances × 2). Queue B (Corner): 23 tests (all 23 non-stub instances × 1). No instances skipped — all passed PRD-first two-condition filter. Excluded 7 corner stubs (excluded_because). Every docstring carries verbatim PRD citation + Design: tag. 59 tests collect under pytest.

## Step 6: Generate implementation — 2026-07-28T12:05:00.000Z

workspace/implementation/: app.py (single-file, all 48 endpoints), requirements.txt (Flask==3.0.3), start.sh (guarded dep install, exec python3 app.py, $PORT default 10000, binds 0.0.0.0).
48 routes = 48 scaffold/PRD. In-memory dicts only; reset_state() at module load, no seeding. Logical clock default 2026-05-01T00:00:00Z; system timestamps .000Z; input datetimes stored raw + echoed verbatim. Connection: close on every response; threaded=True. Decimal/ROUND_HALF_UP money, basis-point, per-reservation-then-sum refund. Smoke-tested: auth, SoD, permit lifecycle, pricing est=250/400, occupancy settle, citation late 7500→9375, event activation cascade full refund + zone SUSPENDED + reservation CANCELLED_BY_EVENT, OCC ERR_STALE_VERSION, capacity conflict, precedence, pagination, lightweight entities.

## Step 7: Test + fix loop — 2026-07-28T12:30:00.000Z

All 8 rounds pass 59/59. Clean sweep. Iterations run: 2 (baseline + 1 fix sweep). NOT strictly clean (1 impl fix).
Tests deleted: None (no PRD-silence or non-unique-derivability issues).
Fixes to test_helpers/: None.
Fixes to implementation/ (app.py): one consistent failure across all 8 baseline rounds — test_zone_create_unknown_designation_rejected expected ERR_INVALID_ENUM but impl returned ERR_VALIDATION for bad zone designation. PRD §2.9 general rule: "An enum field that carries a value outside its permitted set ... is reported as ERR_INVALID_ENUM" (target_status/decision/violation_type illustrative, not exhaustive). designation is unambiguously an enum (§3.1). Impl had routed the 3 named enums to ERR_INVALID_ENUM but inconsistently routed other enum-membership fields to ERR_VALIDATION. Fixed all genuine enum-membership violations to ERR_INVALID_ENUM for consistent §2.9 behavior: create_zone.designation, redesignate.designation (enum check stays before OCC/ERR_STALE_VERSION, preserving §2.9 precedence), create_permit.requested_designation, create_permittee.permittee_type. Range/numeric constraint failures (capacity_slots, day_of_week, minute bounds, datetime ordering) correctly left as ERR_VALIDATION. No checks weakened, no data seeded, no non-PRD capability added.

## Step 8: Finalize PRD — 2026-07-28T12:33:00.000Z

Output: workspace/PRD_FINALIZED.md. PRD.md 273 → 273 lines (one line revised in place, 0% line delta).
Change: §2.9 (Validation Ordering and Precedence) — revise — made the ERR_INVALID_ENUM rule's field list explicitly illustrative and complete: rule applies uniformly to every enum-membership field a client may supply, naming designation (create/redesignate), requested_designation, permittee_type alongside original target_status/decision/violation_type (impl app.py:423,491,572,595,636,1139,1224). Range/type sites (capacity_slots, peak-hour bounds, day_of_week/minute bounds, datetime ordering, expected_zone_version, zone_ids) remain ERR_VALIDATION; server-set enums + list-filter params scoped out. No new mismatch.

## Step 9: Complete PRD — 2026-07-28T12:38:00.000Z

Output: workspace/PRD_COMPLETED.md. PRD_FINALIZED.md 273 lines/42226 chars → 273 lines/42790 chars (+564 chars). Ambiguity-pins: 3. Mismatch-revisions: 0.
- §2.3 Pagination — insert — ambiguity — sort tie-break: resources sharing created_at sort by creation order (earlier first), matching sort_by_created (created_at, _seq) key (app.py:258-259).
- §3.5 Sensor Occupancy and Settlement — insert — ambiguity — when multiple CLOSED sessions match a reservation, latest-created (highest _seq) supplies actual_minutes (app.py:1005-1010).
- §3.8 clock paragraph — insert — ambiguity — /_clock/set_current_utc response 200 OK with data={"current_utc": echoed to_iso8601}, not a persisted resource (app.py:401-411).
Left unchanged: slot-count-from-seconds and event-refund-from-seconds are arithmetically identical to PRD minute-based prose; declined broad §2.9 precedence rewrite (only diverges in pathological combined-error inputs, higher-risk than the silence). Note: agent looked for tests under workspace/ (absent) — tests live at task root; auxiliary only, no impact.

## Pipeline complete — 2026-07-28T12:39:00.000Z

FINAL STATUS: PASS. 59/59 tests × 8 parallel rounds, all green. NOT strictly clean (1 impl fix in Step 7: enum-membership error routing → ERR_INVALID_ENUM). Artifacts: SCAFFOLD (+ DIFFICULTY/CORNER designs), PRD.md, PRD_FINALIZED.md (Step 8, 1 edit), PRD_COMPLETED.md (Step 9, 3 pins), test_suite/ + test_helpers/ (59 tests), workspace/implementation/ (Flask, 48 endpoints).


