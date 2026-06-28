# Worklog — task_0686_golf_entertainment_range

## Step 1: Create Task Directory — 2026-06-28T09:25:37.000Z

Directory pre-existed (parallel-run directive: skip directory-scan). Verified `tasks/task_0686_golf_entertainment_range/` and `tasks/task_0686_golf_entertainment_range/workspace/` exist. Using folder verbatim as {task_dir} for all 9 steps. Difficulty: Expert (Step 2 only).

## Step 2: Generate Scaffold — 2026-06-28T09:43:30.000Z

All checks pass. The scaffold package is complete and clean. I did not look at any sibling task under `/tasks/` — the design was generated purely from the scenario description and the scaffold-generator skill specification (plus the skill's own non-normative examples directory and lint script).

Generated a complete **Expert**-difficulty scaffold for **task_0686_golf_entertainment_range** (Golf Entertainment & Driving Range, Topgolf-style). All three files written. `scaffold_lint.py` returns **VERDICT: clean lint** (302 calls scanned across §1.8+§1.9, all conform to §1.5; all 24 FKs have reverse-reachability).

**Complexity profile:** primary archetype temporal_windowing + secondary pricing_engine; **flat** entity topology (FK + filtered-list GETs); **branching** state-machine shape (also exercises cyclic + parallel dimensions); **peer_roles** model; immediate consistency; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, scheduled_deferred_actions.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities:** Venue, Bay, Member, GameCard, GiftCard (immutable, common_fields:false), Reservation, GameSession, EventPackage, FBTab, QueueTicket, Lesson, Charge (immutable ledger).
- **7 state machines** across 6 entities: Reservation (branching, 5 states), GameSession **parallel dimensions** (play_status × billing_status), EventPackage (cyclic QUOTED↔NEGOTIATING), QueueTicket, FBTab, Lesson.
- **2 concurrency rules** (OCC on parent `version`): confirm-stale-Bay, seat_next-stale-Venue — both 412, both with `expected_<parent>_version` input + version bump.
- **7 calculations:** DYNAMIC_BAY_PRICE (3-input non-linear, clamped, ROUND_TOTAL pinned), FB_TAB_TOTAL (nested gratuity-before-tax rounding), EVENT_PRICING (provisional/settled variants), LOYALTY_EARN (provisional/final variants), DEPOSIT_WATERFALL, SCORING (streak bonus), NO_SHOW_FEE.
- **13 validations** (priority-ordered, 8 categories), **55 endpoints** (incl. `/_clock/set_current_utc` defaulting to 2026-04-01T00:00:00Z), **18 error codes**, **3 roles** (Guest=entity_backed:Member; FrontDesk, RangeManager=opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 Difficulty Rules × **2 instances = 18 instances**, each grounded in declared §1.1–§1.7 elements with pre-computed literal asserts (bay price 6800/5100/9356/10000, FB total 5236, event final 133700, loyalty 102, waterfall refund 6300, no-show 3400).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **40 instances** (36 full recipes + 4 `excluded_because` stubs) across all 9 claim-extraction sections.

## Step 3: Copy Shared Files — 2026-06-28T09:43:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0686_golf_entertainment_range/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-28T09:49:48.000Z

PRD generated at `workspace/PRD.md` (295 lines, 47311 bytes). 5 top-level sections (Introduction, Global Specifications, Business Logic & Workflows, Endpoint Definitions, Error Code Catalogue); 10 §2 subsections, 12 §3 subsections. §4 endpoint table = 55 rows (all 55 scaffold endpoints, paths byte-for-byte). §5 error table = 18 rows. All three hard contracts PASS: Field coverage (76/76 identifiers), Rule coverage (13 validations, 2 OCC, all state machines, 7 calculations, all cascades, sibling-branch symmetry), Path purity (§3 has 0 path/method tokens). Confirmed: SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were NOT read.

## Step 5: Generate Unit Tests — 2026-06-28T10:05:30.000Z

Complete test infrastructure in `test_helpers/` + `test_suite/`. **72 tests total.** Queue A (Difficulty) = 38 tests covering all 18 instances (≥2 each): dual-variant calc (event pricing & loyalty), 3-input clamped dynamic-price, FB-tab nested rounding, branching reservation terminals, event-package revision loop, depth-2/3 cascades (seat_next, session-end), validation-precedence pairs (state>temporal, safety>fiscal), 120-min late-cancel boundary, exact-5 scoring streak, cross-entity state deps, half-open overlap, wallet/gift-card conservation. Queue B (Corner) = 34 tests covering all 36 non-stub instances (≥1 each). **0 instances skipped** — all passed PRD-first two-condition filter. 4 `excluded_because` stubs correctly not translated. Files — test_helpers: `__init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py`; test_suite: `conftest.py, test_01_pricing_and_calculations.py, test_02_state_machines_and_cascades.py, test_03_constraints_and_overlaps.py, test_04_money_invariants_and_boundaries.py, test_05_crud_rbac_occ_and_sweep.py`. 72 tests collect cleanly; every test carries exactly one `Design:` tag; all 96 quoted PRD segments verified verbatim. **NOTE for implementer:** non-trivial `api_prefix` = `/golf` — every endpoint path embeds `/golf`. Flag: `ERR_VALIDATION_RANGE` (422) for `peak_demand_factor` out-of-range and negative shot `points`, distinct from `ERR_INVALID_REQUEST` (400); §2.6 priority hierarchy omits 422.

## Step 6: Generate Implementation — 2026-06-28T10:05:30.000Z

Complete Python + Flask implementation in `workspace/implementation/` (23 files). Launcher: `start.sh`, `requirements.txt` (flask==3.0.3). Foundation: `app.py`, `db.py`, `clock.py`, `errors.py`, `response.py`, `middleware.py`. 10 route modules, 4 service modules (`calc.py` with all 7 calc rules, `serialize.py`, `validate.py`, `lookup.py`). All 54 PRD endpoints implemented (55 route handlers). **Storage:** in-memory dicts keyed by UUID, no seeding, empty on every boot. **Clock:** logical clock default `2026-04-01T00:00:00Z`, advanced only via `POST /golf/_clock/set_current_utc`. **Concurrency:** OCC on confirm (`expected_bay_version`) and seat_next (`expected_venue_version`) → `ERR_STALE_VERSION` (412). Money math: Decimal + ROUND_HALF_UP; loyalty floor. start.sh reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec python3 app.py`. NOTE: all routes mounted under `/golf` prefix. Three flagged PRD-fidelity decisions: (1) HOLD creation does not reject bay-window overlap (only confirm does); (2) venue open/close-hours not enforced as hard rejection; (3) deposit waterfall uses FB tab total_cents per PRD §3.10 (refund differs from corner-design's stated value, PRD wins).

## Step 7: Run Tests and Iterate — 2026-06-28T10:19:03.000Z

All 8 parallel rounds now pass 72/72. Done.

**Iterations run:** 2 (initial diagnostic sweep, then one fix batch + verification sweep).

**Failing tests (4 distinct, each failing 8/8 rounds — consistent, not flaky):** the apparent "union of 72" in the first pass was a counting artifact (script keyed on `outcome` instead of the actual `status` field). The real failures were 4 deterministic ones.

**Tests deleted:** none. All four failures traced to verbatim, uniquely-derivable PRD rules; deletion was never warranted.

**Fixes applied to test_suite/ (STEP 2 — test bugs, made more faithful to PRD):**
- `test_01_pricing_and_calculations.py` — `TestEventPricingDualVariant.test_provisional_and_settled_totals_diverge` and `test_deposit_waterfall_overflow_refunds_remainder`: hardcoded expectations assumed the closed catering tab contributed only its raw subtotal (8200). PRD §3.10 says settlement adds "the sum of `total_cents` over all closed F&B tabs," and PRD §3.9 defines `total_cents` = subtotal + gratuity(18%) + tax(8.25%) = 8200+1476+798 = 10474. Corrected `final_total_cents` 133700→135974, `deposit_refund_cents` 6300→4026, organizer wallet 66300→64026 (plus docstrings).
- `test_03_constraints_and_overlaps.py` — `TestStateBeatsTemporal._setup_cancelled_overlapping_y` and `test_isolated_overlap_returns_window_conflict`: both fixtures created an overlapping HOLD Y *after* confirming reservation X, which PRD §3.3 ("A reservation may not be created on a bay whose window overlaps an already-`CONFIRMED` reservation") forbids. Reordered so Y is created while X is still a HOLD (no conflict), then X is confirmed — the overlap then surfaces at Y's confirm time, exactly as these precedence tests intend.

**Fixes applied to implementation/ (STEP 3 — PRD-required behavior that was missing/wrong):**
- `routes/reservations.py` — `create_reservation`: added the create-time bay-window overlap check (priority 7, `ERR_BAY_WINDOW_CONFLICT`) required verbatim by PRD §3.3 line 144. It was previously omitted (only enforced at confirm). This fixes `test_overlapping_reservation_rejected`.
- `services/serialize.py` — `_available_bay_count`: was computing `len(actual_bays) - occupied`; PRD §2.10 defines it as the venue's declared `bay_count` minus its OCCUPIED/OUT_OF_SERVICE bays. Changed the base from the count of created Bay entities to `v["bay_count"]`. This fixes `test_create_venue_returns_201_with_computed_counters`. Verified seat-next availability logic uses actual AVAILABLE bays independently, so the roll-up change has no functional side effects, and no other test asserts a concrete `available_bay_count` value.

**Final state:** 8/8 parallel rounds, 72/72 tests each, zero failures. Results files cleaned up.

## Step 8: Finalize PRD — 2026-06-28T10:21:11.000Z

`PRD_FINALIZED.md` produced (cp of PRD.md). **0 line delta (0.0%)** — files byte-identical; no edits warranted. Every `<step_7_diff>` item traces to behavior PRD already determines verbatim, not a silence/mismatch:
- create-time bay-window overlap check (`routes/reservations.py`) — PRD §3.3 line 144 states it verbatim; §2.6 already pins priority 7. Fix brought impl up to PRD.
- `_available_bay_count` base (`services/serialize.py`) — PRD §2.10 line 116 states "`bay_count` minus the number of its bays that are `OCCUPIED` or `OUT_OF_SERVICE`" verbatim. Fix brought impl up to PRD.
- four test_01/test_03 fixes — fixture/test bugs corrected to honor PRD rules already stated verbatim (§3.9 `total_cents`, §3.10 settlement, §3.3 overlap precedence); no tests deleted; not PRD silences.
Mandatory pre-edit enumeration performed for both candidate subjects (overlap paths: create/confirm/lesson/lookup; available-count paths: serialize roll-up vs seat_next availability gate) — all consistent with PRD prose, no adjustment needed. Result: a fresh implementer reading PRD_FINALIZED.md alone reproduces current impl behavior.

## Step 9: Complete PRD — 2026-06-28T10:24:31.000Z

`PRD_COMPLETED.md` produced (cp of PRD_FINALIZED.md). 295 lines, +772 chars. **1 mismatch-revision, 4 ambiguity-pins** (one edit pins two values):
- §3.3 Reserving a Bay — revise — mismatch — open/close-minute bounds are advisory; window outside venue hours is accepted, not `ERR_INVALID_REQUEST` (`routes/reservations.py:26-41` `_validate_window`).
- §3.6 Game Sessions (loyalty on end) — insert — ambiguity — "net amount" = realizing reservation's `quoted_price_cents` when `reservation_id` present, else walk-in bay fee 0; provisional reversal uses same basis (`routes/sessions.py:158-169, 141-148`).
- §3.8 Session Settlement — insert — ambiguity — settle `pay_source` defaults to `CARD_ON_FILE`; walk-in bay fee = 0 cents (`routes/sessions.py:181, 29, 197`).
- §3.10 Event Settlement (settle) — insert — ambiguity — `actual_attendee_count` minimum of 1 (`routes/event_packages.py:159`).
- §3.10 Event Settlement (charge) — insert — ambiguity — `EVENT_SETTLEMENT` charge `pay_source` = `CARD_ON_FILE` (`routes/event_packages.py:187`).
Left unchanged (PRD already pins): available_bay_count formula, streak/scoring rules, void provisional-earn wording, confirm pay_source restate, §2.5 unused-version rule. Minor non-pinned input validations left as-is (no contradictory PRD claim).

---

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` present on disk. All 9 steps done. Final test state: 8/8 parallel rounds × 72/72 tests passing.
