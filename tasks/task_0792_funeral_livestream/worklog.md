# Worklog — task_0792_funeral_livestream

## Step 1: Create Task Directory — 2026-07-07T18:15:58.000Z

Pre-assigned folder `tasks/task_0792_funeral_livestream` used as-is (Step 1 scan skipped per instructions). Created `workspace/` subdirectory.

## Step 2: Generate Scaffold (Expert) — 2026-07-07T18:43:42.000Z

All three artifacts complete, parse cleanly (yaml.safe_load verified: SCAFFOLD.yaml top-level 13 keys; DIFFICULTY_DESIGN single key; CORNER_DESIGN single key), and pass scaffold_lint.py.

Expert-difficulty scaffold (archetype: temporal_windowing + posture-driven gating; flat topology; parallel/cyclic state shapes).
- Entities: 9 — FuneralHome, Venue, Operator, ServiceOrder (god-entity absorbing stream/guest-link/memorial/recording sub-state), VenueBooking, CameraAssignment, GuestbookEntry, Donation, TributeVideo. 14 FKs, all with reverse-reachability GETs.
- Endpoints: 35 (34 business + 1 /_clock/set_current_utc test-driving; default clock 2026-03-01T00:00:00Z).
- State machines: 6. ServiceOrder genuinely parallel (broadcast × settlement × stream × recording × memorial axes on one row); TributeVideo cyclic (CHANGES_REQUESTED↔SUBMITTED revision loop); plus VenueBooking, CameraAssignment, Donation, GuestbookEntry.
- Calculations: 5, two dual-variant: service_billing (estimated-vs-final, tiered overage + priority surcharge — mode a) and donation_ledger (pledged-gross-vs-settled-net, per-donation half-up rounding — mode b); plus recording_duration, stream_credit_ledger, access_lockout.
- Error catalog: 42 (above Expert 18–30 guideline; each load-bearing; error count not lint-gated).
- Roles: 4 — FuneralHome (entity_backed), Operator (entity_backed), PlatformAdmin (opaque), Guest (opaque).
- Concurrency rules: 1 — booking-create-stale-order (OCC on ServiceOrder.version via expected_order_version, ERR_STALE_ORDER_VERSION/412).
- §1.8: 18 instances (all 9 Difficulty Rules × 2). §1.9: 24 instances (20 active + 4 excluded_because stubs).
- Lint verdict: clean (240 calls scanned).
- Deviation flagged: entity count 9 (Advanced band) not 10–15; endpoint ceiling forced folding 1:1 satellites into ServiceOrder; Expert difficulty carried by density/coupling + full 9-rule×2 §1.8.

## Step 3: Copy Shared Files — 2026-07-07T18:43:42.000Z

Copied ./INSTRUCTION.md → tasks/task_0792_funeral_livestream/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-07T18:50:58.000Z

Generated workspace/PRD.md — 304-line prose PRD (Expert). Endpoint cross-check: PRD 35 == scaffold 35.

Sections: §1 Introduction; §2 Global Specifications (11 subsections: RBAC + identity translation all 4 roles, verbatim §2.2 envelope, pagination, common properties/versioning, tenant isolation + left-to-right path resolution, validation precedence, parallel status-axis model, cascading releases + derived-field reconciliation, OCC, cents/rounding precision, logical clock); §3 Business Logic (10 domain-grouped subsections); §4 Endpoint table; §5 Error table.

Documented: 9 entities (common_fields → id/created_at/updated_at/version); 6 state machines (ServiceOrder's 5 parallel axes — broadcast, settlement, stream, recording, memorial — + VenueBooking, CameraAssignment, Donation, GuestbookEntry, cyclic TributeVideo); 5 calculations (tiered service_billing est/final; donation_ledger per-donation half-up + pledged/net rollups; recording_duration ceiling; stream_credit_ledger invariant; access_lockout at 5); 1 OCC rule (expected_order_version → ERR_STALE_ORDER_VERSION 412); 43 error codes documented; 35 endpoints.

Hard-contract reports: Contract 1 Field-Name Coverage 62 ids 0 missing PASS; Contract 2 Rule Coverage all transitions/preconditions/error-IDs/side-effects both billing variants all 5 constants sibling symmetry PASS; Contract 3 §3 Path Purity 299 tokens 0 violations PASS.

Ambiguities resolved: (1) POST /service-orders/{id}/transitions authorized FuneralHome/Operator/PlatformAdmin at HTTP layer, axis-level actors documented in §3 (Operator drives stream readiness, FuneralHome drives broadcast/recording/memorial); (2) Operator identity tenant check = target home_id vs operator's own home_id; (3) recording_duration_minutes 0 while actual_end null stated explicitly.

## Step 5: Generate Unit Tests — 2026-07-07T19:06:20.000Z

Generated test_helpers/ (9 files) + test_suite/ (10 test files + conftest.py): 58 test functions. All compile, pytest collects all 58.

test_helpers/: types.py (9 entity TypedDicts + 15 status/role enums), api_client.py (ApiClient one method per 35 endpoints), api_errors.py (ApiErrorId 43 errors + HTTP status map), assertions.py, factories.py (input-field-only payloads), constants.py (billing/donation/lockout thresholds), test_users.py (opaque PlatformAdmin/Guest constants + make_funeral_home_headers/make_operator_headers), fixtures.py (primitive builders + composite tiers: setup_scheduled_order, setup_invoiced_order, run_broadcast, setup_published_memorial_order, setup_settled_donation), __init__.py.

Coverage (verified programmatically): Queue A (Difficulty) all 18 instances × exactly 2 tests = 36; Queue B (Corner) all 20 non-stub instances ≥1 each = 22. All 4 excluded_because stubs' cross-refs resolve; no placeholders. Every test one Design: tag; 0 untagged/dual-tagged.
Instances skipped: none — all 18 difficulty + 20 corner passed PRD-first two-condition filter (both priority_pair_validation_conflict survived via PRD §2.6 explicit fixed validation precedence).
Quality gates: all compile; pytest collects 58; every docstring PRD quote survives verbatim whitespace-normalized grep (fixed 4 initial spliced quotes).

## Step 6: Generate Implementation — 2026-07-07T19:06:20.000Z

Built Python + Flask impl in workspace/implementation/: app.py (single-file, all 35 endpoints), requirements.txt (flask), start.sh (executable).
start.sh: set -euo pipefail, cd script dir, pip install guarded behind `if ! python3 -c "import flask"`, exec python3 app.py. app.py reads $PORT (default 10000), binds 0.0.0.0, foreground threaded=True. In-memory dicts only, no seeding, empty each boot.
State machines: ServiceOrder 5 parallel axes (broadcast DRAFT→SCHEDULED→LIVE→ENDED/CANCELLED; settlement UNBILLED→INVOICED→PAID/VOID; stream PENDING↔READY↔FAILED; recording NONE→RAW→EDITING→READY→DELIVERED; memorial DRAFT→PUBLISHED→ARCHIVED) + VenueBooking, CameraAssignment, Donation, GuestbookEntry moderation, cyclic TributeVideo (revision-count increment on resubmit).
Calc/side effects: tiered service billing (est vs final, 120-min included, 60-min tier1@100¢, tier2@150¢, base 15000¢, 5000¢/camera, 10000¢ priority surcharge, integer cents); per-donation fee round_half_up(gross*0.029)+30 net rollups reconciled onto order+home; stream-credit ledger (consume at SCHEDULE, refund at SCHEDULED-cancel, never <0); ceil recording duration from logical clock; access-lockout at exactly 5; cancel cascade bookings→RELEASED→camera→RELEASED; OCC via expected_order_version; per-mutation version/updated_at bumps.
Faithfulness note flagged: per PRD §3.9 prose, donation fee_cents/net_amount_cents left null until SETTLE (not pre-computed at pledge).

## Step 7: Run Tests and Iterate — 2026-07-07T19:12:14.000Z

All 8 rounds pass 58/58 (verified from results.1..8.json). Clean sweep.

Iterations run: 2 full 8-round sweeps (16 rounds total, each run as 2 waves of 4 to avoid single-task host self-saturation).
Outcome: all 58 tests pass in all 8 rounds of the final sweep.
Anomaly diagnosed: in the first sweep, test_list_operators_pagination_envelope (test_10, last test) failed in rounds 1–3 — but only ever as ERROR at setup ("API server could not be restarted before..."), a per-test-server boot-timeout, not an assertion failure; test body never executed. Verified app is not slow: cold start boot-to-first-response ~0.21s. start.sh already guards pip install behind flask-import check. Failures were the documented spurious host-saturation signature from concurrent waves, not a real bug.
Fixes applied: NONE. 0 tests deleted, 0 test_helpers/ changes, 0 implementation/ changes. Re-run sweep (16/16 waves clean, 58/58 every round) confirms stability.

## Step 8: Finalize PRD — 2026-07-07T19:12:14.000Z

SKIPPED per skip condition: Step 7 exited with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced. Step 9 still runs (full impl scan) per its no-skip rule.

## Step 9: Complete PRD — 2026-07-07T19:18:06.000Z

Produced workspace/PRD_COMPLETED.md (started from PRD.md since PRD_FINALIZED.md absent). 304 → 304 lines (all in-paragraph, no new sections). Char delta +2539. Counts: 10 ambiguity-pins, 1 mismatch-revision.

Changes:
- §2.3 Pagination — insert — ambiguity — pinned out-of-range handling (limit clamped [1,100], negative offset→0, non-integer→ERR_VALIDATION) + created_at tie-break by insertion sequence — app.py:288-303.
- §2.4 Versioning — revise — ambiguity — pinned version initial value 1 — app.py:126.
- §2.5 Tenant Isolation — insert — ambiguity — list endpoints apply tenant isolation as silent filter (empty page), not error — app.py:503-509,555-559.
- §3.3 Opening a Service Order — insert — ambiguity — estimated_cost_cents/final_invoice_cents null until scheduling/invoicing — app.py:640-641.
- §3.4 Reserving the Venue — revise — mismatch — conflict test excludes same order's own bookings (superseded) — app.py:933,419.
- §3.6 Broadcast Lifecycle — insert — ambiguity — exact action token vocabulary (SCHEDULE…ARCHIVE_MEMORIAL, unknown→ERR_VALIDATION) + per-action role matrix (Operator limited to SET_STREAM_READY/FAILED, GO_LIVE, END) — app.py:690-704,736-738.
- §3.8 Recording Delivery — insert — ambiguity — DELIVER_RECORDING may carry delivery_email written before non-null check — app.py:864-867.
- §3.9 Guest Link Access — insert — ambiguity — correct password returns service-order resource HTTP 200 — app.py:894.
- §3.9 Guestbook — insert — ambiguity — decision tokens APPROVE/HIDE (else ERR_VALIDATION) — app.py:1153.
- §3.9 Donations — insert — ambiguity — fee_cents/net_amount_cents null until settlement + action tokens SETTLE/REFUND — app.py:1195-1196,1244.
- §3.10 Tribute Video — insert — ambiguity — action tokens SUBMIT/REQUEST_CHANGES/APPROVE/PUBLISH + per-action roles (REQUEST_CHANGES/APPROVE PlatformAdmin-only) — app.py:1274-1279,1342-1344.

Key gap closed: PRD never enumerated action/decision token strings for the four transition endpoints (largest source of silence) — now pinned. Behaviors already uniquely pinned by PRD (billing tiers, fee rounding, cascade releases, credit ledger, lock threshold, logical clock, validation precedence) left unchanged.

## Pipeline complete — 2026-07-07T19:18:06.000Z

All steps done. Final state: 58/58 tests pass across all 8 stability rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md, PRD_COMPLETED.md (no PRD_FINALIZED.md — Step 8 skipped), test_helpers/ (9 files), test_suite/ (10 files + conftest), workspace/implementation/ (app.py, start.sh, requirements.txt).
