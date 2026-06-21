# Worklog — task_0305_personal_chef_in_home_dining

## Step 1: Create task directory — 2026-06-11T22:28:00.000Z

Created `tasks/task_0305_personal_chef_in_home_dining/` and `tasks/task_0305_personal_chef_in_home_dining/workspace/` using the pre-allocated path (no index scan / auto-increment). Scenario: Personal Chef & In-Home Dining Booking. Target difficulty: Expert (passed only to Step 2 scaffold-generator).

## Step 2: Generate scaffold (Expert) — 2026-06-11T22:59:00.000Z

Generated all three Expert-difficulty scaffold artifacts for **task_0305_personal_chef_in_home_dining**. All pass `scaffold_lint.py` with **VERDICT: clean lint** (443 calls scanned, 0 violations, all 15 FKs reverse-reachable).

**Design choices:** Primary archetype `pricing_engine` × secondary `temporal_windowing`; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency. Notably uses **flat entity topology** and **parallel state-machine shape** (both flagged by §0.3 as under-represented / prioritized). `api_prefix: /` with every entity as a peer top-level collection; FK reverse-reachability via filtered-list GETs.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities**: Chef, MenuPackage, TravelZone, AvailabilityBlock, Client, Booking, GroceryRun, Payment, RecurringPlan, RescheduleRequest
- **6 state machines over 5 entities**: Chef (linear+revert), Booking lifecycle × Booking payment_status (parallel dimensions), GroceryRun (linear+void compensation), RecurringPlan (cyclic ACTIVE↔PAUSED), RescheduleRequest (branching)
- **1 concurrency rule** (OCC on `Chef.version` for booking confirm, 412)
- **10 calculations** (tiered grocery markup, estimated vs actual ingredient cost with per-line round-then-sum, labor small-party surcharge, quote/deposit/balance, lead-time cancellation refund, dual chef reliability scores projected vs settled, payout invariant)
- **13 validations** (priority-ordered auth→existence→ownership→state/OCC→safety→constraint→temporal→capacity→fiscal→shape)
- **46 endpoints** (incl. 1 test-driving `/_clock/set`)
- **29 error codes**, **3 RBAC roles** (Chef/Client entity-backed, PlatformAdmin opaque)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml:** all 9 §0.5 rules × **2 instances = 18**, each with executable `setup_api_calls` chains and code-computed literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml:** **31 active corner instances + 1 excluded_because stub** across 8 guide sections (entities, state_machines, calculations, validations, errors, rbac, cross_cutting_complexity_layers, consistency_model).

**Key correctness work:** caught and fixed two issues during generation — (1) the reliability score clamped at the ceiling making projected/settled non-divergent (lowered BASE_SCORE to 50 and switched the penalty to chef-DECLINE, which IS reachable in this model); (2) initial dual-variant grocery line items happened to round to the estimate value (28320), defeating the divergence claim — replaced with lines yielding actual 29500 vs estimate 28320. All formula-derived assertion literals were verified by executing the §1.3 formulas in code.

Files: SCAFFOLD.yaml (1262 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1248 lines, top key `scaffold_difficulty_design`), SCAFFOLD_CORNER_DESIGN.yaml (1609 lines, top key `scaffold_corner_design`). Verified SCAFFOLD.yaml contains neither design key.

## Step 3: Copy INSTRUCTION.md — 2026-06-11T23:01:00.000Z

Copied root `INSTRUCTION.md` (1424 bytes) into `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-11T23:05:00.000Z

PRD generation complete. Output: `workspace/PRD.md` (~303 lines, 45170 bytes).

**Structure:** 5 top-level sections (§1 Introduction, §2 Global Specs, §3 Business Logic, §4 Endpoints, §5 Error Catalogue); 10 §2 subsections (RBAC, Response Structure, Pagination, Resource Identity/Versioning, OCC on Confirmation, Monetary Precision, Calendar Occupancy/half-open intervals, Nested Lookups, Validation Ordering, Cascades & Conserved Quantities); 11 §3 subsections (chef lifecycle, catalog, booking/confirm cascade, pricing engine, grocery runs, payments/settlement, reliability scores, cancellation cascade, rescheduling, recurring plans, test clock).

**Hard contract results:**
- Contract 1 (Field-Name Coverage): PASS — all 73 required identifiers present verbatim in backticks; 3 initially-missing Client fields (`full_name`, `email`, `dietary_pattern`) added to §3.3.
- Contract 2 (Rule Coverage): PASS — all 29 error IDs in narrative; validation priority ordering stated globally + for 8-step confirm cascade; OCC rule (`expected_chef_version` + current-`version` mismatch + `ERR_STALE_VERSION`/412); calculation constants embedded (1.20, 0.30, tiered 0.25/0.18/0.12 with 20000/50000 boundaries, 86400, refund 1.00/0.50/0.00 with 14/7-day boundaries); per-line round-then-sum vs sum-then-round distinction; settled-vs-projected divergence with pre-clamp basis; deposit pinning; payout invariant; cancellation void cascade; depth-2 plan-pause cascade; reschedule self-hold exclusion.
- Contract 3 (§3 Path Purity): PASS — 140 unique backtick tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combos.

§2.2 emitted verbatim; §4 has 4 columns; §5 has 2 columns; no audit footer.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened/grepped/referenced. No sibling tasks consulted.

## Step 5: Generate unit tests — 2026-06-11T23:08:00.000Z

Test infrastructure generated. **68 tests across 7 test files.**
- Queue A (Difficulty): 36 tests — all 18 difficulty instances covered with exactly 2 tests each (9 rules × 2 instances).
- Queue B (Corner): 32 tests — all 31 non-stub corner instances covered (≥1 each; `occ_stale_chef_version_on_confirm` got 2).

**Instances skipped:** 0 skipped under the PRD-first filter. Every design-index instance had verbatim PRD coverage + unique derivability. The single corner stub `Corner/errors/error_allergen_conflict_on_confirm` was correctly NOT translated (carries `excluded_because`; its cross-reference resolves to a real queue-A instance owning the assertion).

**test_helpers/ files:** `__init__.py` (barrel), `types.py` (10 entity TypedDicts w/ full common-field set per §2.4 + status/role enums), `api_client.py` (44 endpoint methods incl. `/_clock/set`), `api_errors.py` (28 error IDs + status map), `assertions.py` (per-entity + `assert_chef_payout_invariant`), `factories.py` (10 input-only payload factories), `constants.py` (pricing/refund/reliability thresholds + menu-A landmarks), `test_users.py` (entity_backed Chef/Client builders + opaque PlatformAdmin), `fixtures.py` (5-tier composite setup).

**test files:** test_01_entities_crud, test_02_state_transitions, test_03_pricing_and_payments, test_04_confirmation_validations, test_05_cancellation_cascades, test_06_reliability_and_recurring, test_07_security_concurrency + conftest.

**Verification:** every docstring ends with exactly one `Design:` tag, all resolve to real instances (AST audit, 0 untagged/dual-tagged); all PRD citations verbatim-present; no skip/skipif/xfail; all modules compile; `pytest --collect-only` collects all 68 with framework on PYTHONPATH.

**Note for downstream:** `time_conflict_beats_deposit_mismatch_ordering` translated as pure time-conflict assertion (confirm carries no payment body, so fiscal check never runs) — avoiding an unwarranted cross-priority ordering claim, per two-reader rule.

## Step 6: Generate implementation — 2026-06-11T23:08:00.000Z

Implementation complete at `workspace/implementation/`. **13 files:** start.sh (executable), requirements.txt (flask==3.0.3), app.py, db.py, models.py, errors.py, response.py, middleware.py, validators.py, lookups.py, services.py, calculations.py, serialize.py.

**Endpoints implemented: 44** — full PRD §4 coverage across all entities + `POST /_clock/set`.

**Storage:** In-memory only. `db.DB` = one dict per entity collection keyed by UUID. No SQLite/disk/tmp/JSON dump. No seeding/preload — fresh store returns `total_count: 0`. Every start.sh re-invocation wipes state.

**start.sh boot:** `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded install (skip pip if flask importable), `exec python3 app.py`. `app.py` reads `int(os.environ.get("PORT","10000"))`, binds `host="0.0.0.0"` foreground (threaded=True). Cold boot ~8s; warm reboot sub-second.

**Notable decisions:**
- Confirm-path ordering per §2.5/§3.3: version guard → ownership → source-state → chef-ACTIVE → allergen → equipment → party-size → time-conflict → daily-capacity.
- Calc fidelity (smoke-verified): small-party surcharge rounds per-guest before multiply; markup tier whole-subtotal selection (boundary 20000→0.18); estimated grocery rounds once; actual grocery per-line round-then-sum (22 not 23 on drift case); deposit pinned at confirmation on estimated basis; quote re-pins to actual on finalize, back to estimated on void.
- Cascades: cancel computes lead-time refund (full/half/zero boundaries), refunds CAPTURED payments, voids FINALIZED grocery run, releases BOOKING_HOLD, restores active_booking_count, recomputes payout invariant (captured−refunded). Plan-pause depth-2 cascade cancels REQUESTED children at rate 0.
- Reliability: settled (terminal bookings, chrono by event_start_utc then created_at) vs projected (pre-clamp basis + 10 per CONFIRMED/IN_PREP); confirmed projected=60 vs settled=50 w/ one confirmed booking.
- OCC on `expected_chef_version` (mandatory on confirm only, 412 mismatch). Half-open interval overlap w/ prep-buffer widening.

**⚠️ Flag for Step 9 reconciliation:** impl added two not-found codes NOT in PRD §5 — `ERR_BLOCK_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND` (HTTP 404 for GET-by-id on AvailabilityBlock/Payment, which §5 omits but endpoints require). All enumerated PRD codes used verbatim. Step 9 should pin these in PRD_COMPLETED.md if they survive Step 7.

## Step 7: Run tests and iterate — 2026-06-11T23:20:00.000Z

All 8 parallel rounds pass cleanly (67/67 each). Total dropped from 68 to 67 because one test was deleted. Fixes stable across all rounds with zero flakiness.

**Iterations run:** 2 (initial diagnostic sweep + one fix round; the post-fix sweep was clean).

**Initial state:** Each round stably failed the same 4 tests (64/68). After fixes: all 8 rounds pass 67/67.

### Tests deleted (1)
- **`test_reschedule_propose_on_unconfirmed_booking_rejected`** (`test_suite/test_02_state_transitions.py`) — STEP 1b **unique-derivability collapse (ERROR-PRECEDENCE / BRANCH-ASYMMETRIC SILENCE)**. The test asserts the *create/propose* endpoint (`POST /reschedule-requests`) rejects a non-CONFIRMED booking with `ERR_BOOKING_NOT_CONFIRMED`. PRD §3.9 binds `ERR_BOOKING_NOT_CONFIRMED` **only to the accept action** ("A chef accepts a `PROPOSED` request... but only when the parent booking is `CONFIRMED` (`ERR_BOOKING_NOT_CONFIRMED`)"). The create paragraph (§3.9 line 200) describes the body fields and says only "Either party may propose moving a confirmed booking" — descriptive prose binding no error to the create path. The SCAFFOLD confirms this: the `CONFIRMED` precondition is attached to the accept transition, never to the create operation. Two faithful PRD-only implementations diverge (gate at create vs. gate only at accept), so the assertion is not uniquely derivable. Scaffold rule that drove the test: `Corner/state_machines/reschedule_propose_on_unconfirmed_booking_rejected`.

### Fixes applied to `test_suite/` (3 tests — STEP 2 test-faithfulness corrections, all in `test_04_confirmation_validations.py`)
- **`test_confirm_declined_booking_returns_invalid_state_not_allergen`** and **`test_confirm_declined_booking_state_check_precedes_business`** — both confirmed with a **stale** `chef["version"]`. Declining recomputes the chef's reliability scores (PRD §3.7), and recomputing a derived field is a version-bumping mutation (PRD §2.4); the §2.5 version guard (correctly evaluated first) therefore tripped `ERR_STALE_VERSION` instead of the intended `ERR_INVALID_STATE`. Fix: re-read the chef (`get_chef`) after decline and pass its current version, so the version guard passes and the booking source-state check is what trips — isolating the state-vs-allergen ordering the test targets. (Implementation was already PRD-correct.)
- **`test_party_size_below_min_rejected`** — asserted `ERR_PARTY_SIZE_OUT_OF_RANGE` at **booking creation**, but PRD §3.3 places the party-size range check at **confirmation** only (creation requires only `party_size >= 1`). Fix: create the party-3 booking (succeeds, REQUESTED) then confirm it; the rejection now surfaces on the confirm path where the PRD verbatim states it. This keeps the PRD-covered assertion (STEP 1c partial-coverage handling) and makes the test faithful rather than weakening it.

### Fixes applied to `test_helpers/`
- None.

### Fixes applied to `implementation/`
- None. The implementation was PRD-faithful on every failing case; all four failures were test-side (one PRD-silent assertion deleted, three test environments corrected to match PRD-stated rules).

**Final result:** 8/8 parallel rounds pass 67/67 with zero flakiness.

## Step 8: Finalize PRD — align documentation to implementation — 2026-06-12T02:05:44.416Z

(Reconstructed on resume. The original run left `workspace/PRD_FINALIZED.md` on disk as a byte-identical bare copy of `PRD.md` — only Method step 0's `cp` had run, none of the alignment edits, and the worklog entry was missing. Step 8 was therefore re-run properly from the bare copy. Step 8 was NOT skipped: Step 7 had 1 deletion + 3 `test_suite/` fixes, so the skip condition — all four fix categories zero — did not hold. Summary below is the re-run subagent's returned summary, verbatim.)

**Line counts:** PRD.md = 303 lines, PRD_FINALIZED.md = 303 lines, delta = 0 lines (0%). One line revised in place (§3.9, line 200).

**Changes (1):**
- **§3.9 Rescheduling** — *revise* — Clarified that the reschedule *create/propose* path imposes no booking `lifecycle_status` precondition; it checks only ownership, and the `CONFIRMED` requirement (`ERR_BOOKING_NOT_CONFIRMED`) is enforced only at acceptance, not at creation — `implementation/app.py:867-898` (create, no state check) vs. `app.py:938-939` (accept, the only `ERR_BOOKING_NOT_CONFIRMED` gate).

**Per-edit pre-edit search log:**
- (a) **Subject:** The booking-`CONFIRMED` precondition on the reschedule create/propose operation.
- (b) **Impl paths enumerated/read:** `create_reschedule_request` (app.py:867-898) — only checks role ∈ {Client, Chef}, required fields, `end > start`, booking existence, and ownership (caller is a party to the booking); no `lifecycle_status` check. `accept_reschedule` (app.py:927-979) — the sole site raising `ERR_BOOKING_NOT_CONFIRMED` (line 938-939). `reject_reschedule` (982-995) and `withdraw_reschedule` (998-1011) — neither checks booking state, only request `status == PROPOSED` and ownership. Confirmed the create path accepts a request against a booking in any lifecycle state.
- (c) **Wording adjustment:** Changed "moving a confirmed booking" → "moving a booking" and added an explicit clause stating the create operation checks only ownership and does not reject a non-`CONFIRMED` booking, with the `CONFIRMED` requirement enforced "only at acceptance, not at creation." Scoped the negative claim to the create path so it does not contradict the accept path's genuine `ERR_BOOKING_NOT_CONFIRMED` gate (left line 202 verbatim). Did not touch reject/withdraw prose, which the impl leaves state-unrestricted, consistent with the existing text.

**Items intentionally NOT patched (fixture bugs, PRD already determines behavior):**
- **`test_confirm_declined_booking_*` (version-vs-state ordering):** Implementation's confirm ordering (version guard → ownership → state → chef-ACTIVE → ...) already matches PRD §2.5/§3.3 verbatim. The test failure was a stale-version fixture. No PRD silence.
- **`test_party_size_below_min_rejected`:** PRD §3.3 already states booking creation requires only `party_size >= 1` and places the `ERR_PARTY_SIZE_OUT_OF_RANGE` range check at confirmation (§3.3). Implementation matches (`create_booking` uses `minimum=1`; range check at confirm, app.py:539-540). Pure fixture bug. No PRD silence.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-12T02:11:19.306Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` via a full PRD-vs-`implementation/` scan.

**Source vs. completed:**
- `PRD_FINALIZED.md`: 303 lines, 45,505 chars
- `PRD_COMPLETED.md`: 305 lines, 47,667 chars
- Char delta: **+2,162**; line delta: **+2** (the two new error-catalogue rows)

**Counts:** 5 ambiguity-pins, 2 mismatch-revisions (7 edits total).

**Per-change:**
- **§2.8 — insert — ambiguity** — Pinned `ERR_BLOCK_NOT_FOUND` (GET `/availability-blocks/{blockId}`) and `ERR_PAYMENT_NOT_FOUND` (GET `/payments/{paymentId}`), both 404, into the not-found family that previously omitted them — `errors.py:48-49`, `lookups.py:36,66`.
- **§2.9 — revise — mismatch** — The global order declares ownership (5) before state (6), but the impl checks the acted-on resource's own source-state (`ERR_INVALID_STATE`) *before* ownership on plain transition endpoints (decline, cancel, start-prep, complete, finalize, reschedule accept/reject/withdraw, plan pause/resume/cancel); confirm and generate-occurrence stay ownership-first. Pinned this refinement — `app.py:589-592, 606-609, 667-670, 684-687, 846-849, 934-937, 989-992, 1005-1008, 1157-1160, 1182-1185, 1197-1200` vs ownership-first `app.py:519-524, 1106-1109`.
- **§5 — insert — ambiguity** — Added `ERR_BLOCK_NOT_FOUND` (404) and `ERR_PAYMENT_NOT_FOUND` (404) rows to the error catalogue — `errors.py:48-49`.
- **§3.3 — insert — ambiguity** — Pinned that a fresh booking's `cancellation_refund_rate` field starts at 0 (a response field the PRD named only as a computed value) — `app.py:458`.
- **§3.6 — revise — mismatch** — The impl enforces two preconditions absent from the PRD: deposit requires `payment_status == UNPAID` (`ERR_INVALID_STATE`, after the CONFIRMED check, before amount), and balance requires `payment_status == DEPOSIT_PAID` (`ERR_INVALID_STATE`, first, before the finalized-run check). Pinned both, with their relative order — `app.py:716-721` (deposit), `app.py:724-729` (balance).
- **§3.2 — insert — ambiguity** — Pinned that a duplicate `zone_code` for a chef is rejected with `ERR_INVALID_REQUEST` (PRD said "unique" but was silent on the code) — `app.py:265-267`.
- **§3.3 — insert — ambiguity** — Pinned that a duplicate client `email` is rejected with `ERR_INVALID_REQUEST` — `app.py:383-385`.

**Verification:** Cross-checked every error code raised across the implementation (`grep`) against PRD §5 — all 31 are now present in the catalogue. Both flagged not-found codes from the Step 6 note were confirmed defined (`errors.py`) and emitted on real GET-by-id paths (`lookups.py`). Tests were used only as auxiliary cross-reference (they reference none of these codes/orderings, consistent with Step 7 weakening), never as authority.
