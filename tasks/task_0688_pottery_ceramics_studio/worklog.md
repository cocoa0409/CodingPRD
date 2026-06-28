# Worklog — task_0688_pottery_ceramics_studio

## Step 1: Create Task Directory — 2026-06-28T09:25:51.000Z

Directory `tasks/task_0688_pottery_ceramics_studio/` and `workspace/` subdir pre-created (per execution directives; Step 1 directory-scan skipped to avoid parallel-run ID collisions). Verified empty workspace, INSTRUCTION.md present at project root.

## Step 2: Generate Scaffold — 2026-06-28T09:41:20.000Z

All three scaffold artifacts are generated and pass `scaffold_lint.py` with a clean verdict. I did not look at any sibling task directory — the design was derived purely from the scenario and the scaffold-generator skill.

Generated three files under `/home/ubuntu/github/CodingPRD/tasks/task_0688_pottery_ceramics_studio/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile (Expert):** primary archetype workflow_orchestration + secondary quota_allocation (kiln firing capacity); layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; flat topology; branching state machines; peer_roles; immediate consistency.

**Entities (9):** LoyaltyMember, PaintBarItem, StudioVisit, BisquePiece, KilnBatch, PartyBooking, ClassSeries, Enrollment, LoyaltyLedgerEntry (append-only, common_fields:false). Cross-aggregate (BisquePiece→StudioVisit + KilnBatch), polymorphic ledger source_ref, bubble-up ClassSeries↔Enrollment.

**State machines (6):** StudioVisit (OPEN→{SETTLED,VOIDED}), BisquePiece (PAINTED→LOADED→FIRING→READY→PICKED_UP with LOADED→PAINTED un-load cycle), KilnBatch (LOADING→FIRING→COMPLETED / →CANCELLED), PartyBooking (DEPOSIT_PENDING→{CONFIRMED,EXPIRED,CANCELLED}), ClassSeries (OPEN↔FULL→STARTED/CANCELLED cycle), Enrollment (ENROLLED→{ATTENDED,WITHDRAWN,REFUNDED}). One concurrency rule: OCC on KilnBatch.version for piece load (ERR_STALE_BATCH_VERSION, 412).

**Calculations (6):** settle_visit_charge (provisional vs settled variants, pinned circular eval order), visit_points_earned (estimate vs actual, GOLD bonus threshold), supplies_charge (round-per-line-then-sum, bulk break), party_deposit (tiered), enrollment_points_earned (long-series bonus), member_tier (threshold). All numeric test asserts are code-computed literals.

**Validations:** 19 priority-ordered rows (auth → existence → state → business safety/referential/constraint/temporal/fiscal). **Errors:** 19. **Endpoints:** 52 (51 business + 1 `/_clock/set_current_utc` with mandatory default 2026-04-01T00:00:00Z). **Roles (4):** Anonymous, StudioStaff, StudioManager (opaque), LoyaltyMember (entity_backed).

**Difficulty design:** all 9 §0.5 rules × 2 instances = 18, each pair satisfying its differentiation clause. **Corner design:** 39 instances across all 9 claim-extraction-guide sections (37 live + 2 `excluded_because` stubs pointing to valid §1.8 instances).

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint`; 57 unique instance names; OCC version values fixed to come from batch reads.

## Step 3: Copy Shared Files — 2026-06-28T09:41:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0688_pottery_ceramics_studio/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-28T09:47:31.000Z

Generated `workspace/PRD.md` (47798 bytes). Did NOT read the two withheld design files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml).

**Sections:** §1 Introduction; §2 Global Specs (RBAC, fixed response envelope, pagination, common props & logical clock, money/point precision, derived totals, cascades/compensation, nested retrieval & existence ordering, OCC on kiln loading, validation ordering); §3 Business Logic (12 lifecycle subsections); §4 endpoint table (53 endpoints, 4 cols); §5 error catalogue (19 errors, 2 cols).

**Entities documented (9):** LoyaltyMember, PaintBarItem, StudioVisit, BisquePiece, KilnBatch, PartyBooking, ClassSeries, Enrollment (all common-fielded), plus append-only LoyaltyLedgerEntry (id + created_at only).

**Calculation rules in prose:** settle_visit_charge (pinned 4-step order: base sum → tier discount on bisque only rounded once half-up → 1-cent-per-point redemption → total floored at 0); visit_points_earned (1 pt/100 cents floored, ×1.5 floored bonus at ≥10000 cents net); OPEN provisional variant (gross, no discount) vs settled; supplies_charge (qty×unit, 10% bulk break rounded per line when qty≥3); party_deposit (per-head 4500/8000 × guest_count, ×0.25 rounded once); enrollment_points_earned (1 pt/100 cents floored, +50 flat when session_count≥6); member_tier (≥2000 GOLD, ≥500 SILVER else BRONZE, inclusive boundaries).

**Contract reports:** Field coverage PASS (59/59 fields, 39/39 bodies); Rule coverage PASS (6 calcs, 1 OCC, all state machines, 19 errors); Path purity PASS (0 path tokens in §3). §2.2 emitted byte-for-byte.

## Step 5: Generate Unit Tests — 2026-06-28T09:58:42.000Z

Generated complete test infrastructure under the design-index-only contract.

**Stage 1 — test_helpers/ (9 files):** types.py (LoyaltyLedgerEntry omits updated_at/version), api_client.py (58 endpoint methods), api_errors.py (19 error IDs + HTTP map), assertions.py, factories.py, constants.py, test_users.py (opaque role headers + make_member_headers), fixtures.py (composite helpers), __init__.py. Imports cleanly.

**Stage 2 — test_suite/ (conftest + 8 files, 73 test functions):** test_01 settlement & loyalty calc, test_02 kiln & state machines, test_03 cascades & cross-entity (Queue A); test_04–08 entities, transitions, calcs, validations/errors, endpoints/rbac/concurrency (Queue B).

**Coverage:** Queue A (Difficulty): all 18 instances, 2 tests each = 36. Queue B (Corner): all 37 non-stub instances, 1 test each = 37. Every test docstring carries exactly one verbatim Design: tag; bidirectional tag↔instance verified.

**Skipped (per contract):** 2 corner stubs are `excluded_because:` with no test_recipe — Corner/state_machines/pieces_not_ready_blocks_checkout and Corner/errors/stale_batch_version_excluded; both cross-references resolve to live difficulty instances.

**Notable PRD-first adjudication:** Corner/calculations/checkout_total_floored_at_zero — instance's discount_cents==5000 not uniquely derivable (GOLD member adds 10% bisque discount → 5100); test emitted but asserts only settled_total_cents==0 and point_balance==0. Several instances use validate_error_is_one_of([...]) where yaml asserts allow alternative error paths.

## Step 6: Generate Implementation — 2026-06-28T09:58:42.000Z

Built Python + Flask implementation (24 files) in workspace/implementation/.

**Files:** start.sh (guarded-install foreground launcher), requirements.txt (flask==3.0.3), app.py (blueprints + error handlers → structured envelopes), clock.py (logical clock default 2026-04-01T00:00:00Z, never wall-clock fallback), db.py (in-memory dict store + stamp_common/touch, version starts 1), response.py (envelope + pagination limit 10/max 100), errors.py, middleware.py (X-User-ID/X-User-Role auth + RBAC), routes/ (9 entity route modules + clock), services/ (calculations, loyalty, serializers, transitions/cascades/sweeps, visit_calc, validation, lookup).

**Endpoints:** all 52 + POST /_clock/set_current_utc, incl. FK reverse-reachability lists and action/transition endpoints.

**Storage & clock:** in-memory only (dicts), no seeding/preloading (fresh boot total_count 0), state wiped on each start.sh re-invocation. Logical clock 2026-04-01T00:00:00.000Z on boot; created_at/updated_at/ready_at/firing_completes_at read logical clock; envelope meta uses real time. Clock-set runs 3 sweeps (firing completion, booking expiry, series start).

**start.sh:** reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py, pip install guarded behind flask-import check.

**Self-verification:** ran smoke suites covering auth/RBAC/ownership, member registration, walk-in vs party fee, piece lifecycle, bulk discount, OCC 412, firing cascades, two-variant settlement, party deposit, enrollment points/bonus/reversal, tier transitions, clock sweeps, void cascade, pagination. All modules compile.

## Step 7: Run Tests and Iterate — 2026-06-28T10:13:02.000Z

(Orchestrator note: subagent's results.*.json were cleared by the sweep's leading `rm -f`; orchestrator re-ran one confirmation 8-round parallel sweep — all 8 rounds passed 73/73, failed=0, errors=0 — and the results.{1..8}.json files are now durably present.)

**Iterations run:** 2 fix-and-sweep cycles (initial diagnostic sweep + 1 fix + 2 confirmation sweeps). Final state: two consecutive full 8-round parallel sweeps each passed 73/73 with zero failures and zero errors.

**Initial failure set (union across 8 rounds):** 11 unique tests — split into two distinct root causes:
1. **3 deterministic `failed`** in `test_01_settlement_and_loyalty_calc.py` (settlement returned `409 ERR_PIECES_NOT_READY` instead of `200`).
2. **8 flaky `error`** ("API server could not be restarted before [test]") spread thinly across rounds — pure host-saturation from 8 concurrent per-test-server restart storms.

**Tests deleted:** None. No PRD-silence or non-unique-derivability cases were found.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added new helper `fire_pieces_to_ready(visit_id, bisque_prices)` that adds N pieces, loads them all into one batch, and fires the batch to completion so every piece reaches `READY`. (Reason: PRD §3.8's checkout safety gate requires every piece to be `READY`/`PICKED_UP`/`VOIDED` before settlement.)

**Fixes applied to `test_suite/`:**
- `test_01_settlement_and_loyalty_calc.py` — the 3 settlement tests (`test_settled_applies_silver_tier_discount`, `test_settled_pinned_eval_order_silver_no_redeem`, `test_settled_base_components_pinned`) previously used `add_piece(...)` (leaving pieces `PAINTED`) and then checked out, which the PRD-faithful implementation correctly rejects with `ERR_PIECES_NOT_READY`. This was a **STEP 2 test-fixture bug**: PRD §3.8 verbatim says checkout "is blocked with `ERR_PIECES_NOT_READY`" while any piece is "still `PAINTED`, `LOADED`, or `FIRING`." Replaced the bare `add_piece` calls with `fire_pieces_to_ready([6000, 4000])` so the precondition is PRD-faithful (pieces `READY`, same bisque subtotal of 10000). The implementation's check was left untouched.

**Fixes applied to `implementation/`:**
- `workspace/implementation/start.sh` — replaced the per-restart `python3 -c "import flask"` dependency probe (which spawns a full extra cold-import interpreter on every one of the hundreds of per-test reboots) with a sentinel-file gate (`.deps_installed`). This roughly halves Python-startup CPU on the hot path, keeping cold boots inside the runner's 15s restart-poll window under the 8-way concurrent sweep. The sentinel is a dependency-install marker only — no entity data is seeded or persisted; storage remains in-memory and is wiped on every restart. No implementation source/logic was changed; the `ERR_PIECES_NOT_READY` check is PRD-correct and was preserved.

**Key finding on the flakes:** The server itself boots in ~0.4s and is healthy; the "could not be restarted" errors were timing artifacts of 8 simultaneous restart storms saturating the host. Reducing per-restart interpreter spawns eliminated them across two confirmation sweeps.

## Step 8: Finalize PRD — 2026-06-28T10:15:04.000Z

(Step 8 ran because Step 7 made >0 fixes: 1 test_helpers/, 1 test_suite/, 1 implementation/start.sh.)

Traced each Step 7 diff item to its matching behavior in implementation/ — all three accounted for by behavior PRD already uniquely determines, or by test/launcher infrastructure PRD neither describes nor should. **Zero edits made; PRD_FINALIZED.md is byte-identical to PRD.md** (both md5 `b600228d8729a65b5a32607f51e52303`, 295 lines, 0.0% delta).

**Per-item analysis:**
1. test_helpers/fixtures.py `fire_pieces_to_ready` helper — subject: checkout safety gate; impl routes/studio_visits.py:217-221 raises ERR_PIECES_NOT_READY for any piece not in (READY,PICKED_UP,VOIDED), matching PRD §3.8 verbatim. Void cascade (studio_visits.py:289-316) checked for consistency — disjoint state set. PRD §3.8 already pins this. No edit.
2. test_suite/test_01 (3 settlement tests switched add_piece→fire_pieces_to_ready) — same gate; impl studio_visits.py:206-221. Pure fixture-precondition fix. No edit.
3. implementation/start.sh sentinel-file dependency gate — launcher-only (.deps_installed sentinel + exec python3 app.py); no API source/logic touched; storage in-memory, wiped on restart. Not PRD-observable. No edit.

Valid "verbatim copy" outcome — no edits invented to justify the step.

## Step 9: Complete PRD — 2026-06-28T10:21:28.000Z

Full PRD-vs-implementation/ completeness scan. Source `PRD_FINALIZED.md` (295 lines, 47,798 chars) → `PRD_COMPLETED.md` (295 lines, 51,363 chars, +3,565 chars). All edits in-paragraph inline; no new lines/sections.

**Counts:** ambiguity-pins: 11, mismatch-revisions: 3 (14 distinct edited lines).

**Per-change log:**
- §3.3 Notification — insert — ambiguity — payload shape: full piece object + member_contact (member_id/full_name/phone/email, null for anonymous), ERR_INVALID_STATE when not READY/PICKED_UP — routes/bisque_pieces.py:98-121
- §3.8 Points preview — insert — ambiguity — returns visit object with only points_earned overwritten (0 for no-member), mutates nothing — routes/studio_visits.py:110-124
- §3.8 Checkout redemption — insert — ambiguity — ERR_INSUFFICIENT_POINTS (422) for redeeming >0 on anonymous visit; redemption checks run only when points_redeemed>0 after pieces-ready gate — routes/studio_visits.py:228-238
- §3.7 Paint-bar add — insert — ambiguity — reorder_threshold optional, non-negative, default 0 — routes/paint_bar_items.py:40
- §3.4 Load ordering — insert — ambiguity — owning-visit-OPEN check fires last (after stale-version) with ERR_VISIT_NOT_OPEN (409) — routes/kiln_batches.py:124-131
- §3.4 Kiln batch create — revise — ambiguity — turnaround_hours non-negative integer default 48 — routes/kiln_batches.py:44
- §3.6 Pay-deposit — insert — ambiguity — clock-before-scheduled_for check fires after state with ERR_INVALID_STATE (409), before amount-mismatch — routes/party_bookings.py:112-122
- §3.6 Expire — insert — ambiguity — manual expire before scheduled_for → ERR_INVALID_STATE (409) — routes/party_bookings.py:140-141
- §3.11 Start series — insert — ambiguity — manual start while not OPEN/FULL or before starts_at → ERR_INVALID_STATE (409) — routes/class_series.py:176-180
- §3.10 Enroll state — insert — ambiguity — FULL→ERR_SERIES_FULL, STARTED/CANCELLED→ERR_INVALID_STATE, in order — routes/class_series.py:114-122
- §3.10 Enroll ownership — insert — ambiguity — ERR_NOT_RESOURCE_OWNER for member enrolling a different member_id, after existence/before state/business — routes/class_series.py:109-110
- §3.8 Checkout state — insert — ambiguity — non-OPEN checkout → ERR_INVALID_STATE (409) — routes/studio_visits.py:214-215
- §3.9 Void state — insert — ambiguity — non-OPEN void → ERR_INVALID_STATE (409) — routes/studio_visits.py:286-287
- §3.7 Consume request — revise — ambiguity — qty minimum 1 — routes/studio_visits.py:169
- §3.7 Consume response — insert — ambiguity — consume returns 201 with updated studio-visit object — routes/studio_visits.py:202
- §3.4 Load response — insert — ambiguity — successful load returns 200 with bisque-piece object — routes/kiln_batches.py:139
- §3.1 Member email — revise — MISMATCH — PRD called email "unique"; impl does not enforce, revised to state uniqueness not enforced — routes/loyalty_members.py:31-52
- §3.7 Item sku — revise — MISMATCH — PRD called sku "unique"; impl does not reject duplicates, revised — routes/paint_bar_items.py:31-56
- §3.6 Booking host — revise — MISMATCH — PRD required host "ACTIVE"; impl checks existence only, revised (SUSPENDED member may host) — routes/party_bookings.py:42
- §3.6 Booking validation order — insert — ambiguity — guest-count-min (ERR_INVALID_REQUEST) before future-date (ERR_BOOKING_DATE_PAST) — routes/party_bookings.py:46-58

State-transition errors not individually pinned (unload, pickup, mark-attended, withdraw, firing transitions, cancels, suspend/reactivate) already covered generically by §2.10's ERR_INVALID_STATE rule and matched by impl — no edits needed.

---

## PIPELINE COMPLETE — 2026-06-28T10:21:28.000Z

All 9 steps complete. Final 8-round parallel stability sweep: 73/73 passed in every round (failed=0, errors=0). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.{1..8}.json}.
