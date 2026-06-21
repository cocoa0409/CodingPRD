# Worklog — task_0182_reward_crowdfunding

## Step 1: Create Task Directory — 2026-06-06T04:31:07.000Z

Created `tasks/task_0182_reward_crowdfunding/` and `tasks/task_0182_reward_crowdfunding/workspace/`. Directory specified explicitly by user (no tasks/ scan). Difficulty: Expert (passed only to Step 2 scaffold generator).

## Step 2: Generate Scaffold (Expert) — 2026-06-06T04:56:00.000Z

All three Expert-level scaffold artifacts are generated and pass a clean `scaffold_lint.py` run.

Generated the **Reward Crowdfunding (Expert)** scaffold:

**SCAFFOLD.yaml** (§1.0–§1.7):
- **Entities: 11** — Creator, Backer, Campaign, RewardTier, StretchGoal, AddOn, Pledge, PledgeAddOn (junction), PaymentAuthorization (event), Refund (event), FulfillmentSurvey. Archetype: quota/allocation + event-sourcing; topology hierarchical with cross-aggregate Backer/Creator refs.
- **State machines: 5** — Campaign (branching DRAFT→LIVE→CLOSING→{SUCCESSFUL|FAILED}, +CANCELED), Pledge `payment_status` × `fulfillment_status` (parallel dimensions), RewardTier (cyclic AVAILABLE↔SOLD_OUT→RETIRED), StretchGoal (cyclic LOCKED↔UNLOCKED).
- **Calculations: 11** — dual-variant projected_raise vs settled_raise (Campaign), provisional vs final backer_reliability_score (Backer), pledge_total (mode-a combinatorial: zone/weight/cap), platform_fee (mode-b round-per-pledge-then-sum), plus tier/addon claimed-quantity, stretch unlock, two interval-overlap geometries, lifetime contribution.
- **Validations: 18** (priority-ordered, auth→existence→referential→state→temporal→constraint→OCC).
- **Endpoints: 38** (2 test-driving: `/_clock/set`, `/_clock/advance`); flat `api_prefix: ""` so all 12 FKs get filtered-list reverse-reachability GETs.
- **Errors: 20** (all referenced by a validation/transition). **Roles: 3** (PlatformAdmin opaque; Creator/Backer entity_backed, peer_roles). **Concurrency: 1** OCC rule (pledge-create stale campaign.version, 412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rules × 2 = **18 instances**, all formula-derived asserts precomputed as literals (e.g. projected 16950 vs settled 11300; fee 566 not 565; payout 10734; reliability 100.0→0.0).

**SCAFFOLD_CORNER_DESIGN.yaml** — 7 sections, **26 instances** (23 executable + 3 `excluded_because` stubs referencing §1.8 by name).

Validation: `scaffold_lint.py` → **VERDICT: clean lint** (304 calls scanned). All grounds resolve into §1.1–§1.7; all instance names unique across both files (44); no forbidden concurrency vocabulary; Rule 8 satisfied by two genuinely different interval semantics (Creator half-open live-window with adjacency allowed vs RewardTier early-bird buffer-gap rejecting adjacency).

Design note flagged: Rule 8 (temporal overlap) is not native to crowdfunding, so two plausible-but-added mechanics were introduced — a per-creator concurrent-LIVE-campaign window rule and an early-bird tier availability-window buffer rule (new fields `is_early_bird`/`available_from`/`available_until` on RewardTier). These are the most synthetic part of the scaffold.

## Step 3: Copy Shared Files — 2026-06-06T04:59:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0182_reward_crowdfunding/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T05:03:00.000Z

PRD generated: `workspace/PRD.md`. All three hard contracts pass.

**Structure**: 5 top-level sections, 270 lines. §2 has 8 subsections (RBAC, fixed §2.2 envelope, pagination, identity/versioning, precision/rounding, nested-path resolution, OCC, cascading consistency). §3 has 12 lifecycle-ordered subsections (registration → tiers/early-bird → stretch goals → add-ons → pledging → shipping math → backer reliability → auth queue/clock → settlement fork → campaign cancel → fulfillment → launch gate). §4 = 4-column endpoint table (39 endpoints); §5 = 2-column error table (20 errors).

**Entities covered (11)**: Creator, Backer, Campaign, RewardTier, StretchGoal, AddOn, Pledge, PledgeAddOn, PaymentAuthorization, Refund, FulfillmentSurvey — including the three event records (`PledgeAddOn`, `PaymentAuthorization`, `Refund`) flagged as having only `id`/`created_at` (no `updated_at`/`version`).

**State machines covered (5)**: Campaign (DRAFT→LIVE→CLOSING→SUCCESSFUL/FAILED/CANCELED, branching fork by funding_model×goal_met), Pledge.payment_status, Pledge.fulfillment_status (parallel axes), cyclic RewardTier AVAILABLE↔SOLD_OUT→RETIRED, cyclic StretchGoal LOCKED↔UNLOCKED. All transition preconditions paired to error IDs; all side-effect cascades (including the depth-3 failed→refund→inventory-release) stated.

**Calculations covered (9)**: pledge_total (subtotal + tiered/capped shipping, ceil-to-kg), platform_fee (per-pledge round-half-up-then-sum, pinned order, 0.05), projected vs settled raise (dual-variant), backer_reliability_score (provisional vs final divergence), backer_lifetime_contribution (optimistic vs realized), tier/addon claimed_quantity, stretch_goal_unlock, campaign_window_overlap (half-open, adjacency allowed) vs tier_window_overlap (3600s buffer gap, adjacency rejected).

**Validations**: all 18 priority-ordered checks rendered; the pledge-create chain's full precedence stated explicitly in §3.5. OCC rule (`expected_campaign_version` → `ERR_STALE_CAMPAIGN_VERSION`/412) framed purely in stale-version terms.

**Contract reports**: Contract 1 (Field-Name Coverage) 58/58 PASS; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) 357 backtick tokens / 0 slash-paths PASS; §2.2 byte-identical.

**Ambiguous/hard-to-render**: (1) two interval-overlap rules have opposite adjacency semantics — rendered with explicit cross-reference. (2) `ERR_CURRENCY_MISMATCH` is actually a same-campaign add-on check (phrased as campaign-membership). (3) campaign-cancel distinguishes AUTHORIZED (refunded) vs PENDING_AUTH (voided) pledges, both ending CANCELED — rendered explicitly.

## Step 5: Generate Unit Tests — 2026-06-06T05:07:00.000Z

Generated complete test infrastructure (Expert) purely from the four task inputs + the unit-test-generator skill.

**test_helpers/ (Stage 1) — 9 files:** `__init__.py` (barrel export), `types.py` (entity TypedDicts + status enums; append-only entities PledgeAddOn/PaymentAuthorization/Refund correctly omit updated_at/version), `api_client.py` (one method per endpoint), `api_errors.py` (20 error IDs + HTTP status map registered), `assertions.py`, `factories.py`, `constants.py` (shipping ladder, fee rate, tier-gap), `test_users.py` (opaque PlatformAdmin + entity_backed Creator/Backer builders), `fixtures.py` (composite lifecycle helpers with identity threading and OCC-version re-reading).

**test_suite/ (Stage 2) — conftest.py + 4 test files, 59 tests total:** test_01_campaign_skeleton.py (13), test_02_launch_and_windows.py (8), test_03_pledging_and_inventory.py (18), test_04_settlement_and_cascades.py (20)

**Coverage:** Queue A (Difficulty): 36 tests — all 18 instances covered exactly 2 each (9 rules × 2 instances). Queue B (Corner): 23 tests — all 23 non-stub instances covered ≥1 each (no extras, no gaps).

**Skipped instances: 0 non-stub instances skipped.** Every difficulty and corner instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability). The 3 queue-B `excluded_because:` stubs were not translated; cross-references all resolve to real difficulty instances.

**Audits passed:** all files compile; every test has exactly one verbatim `Design:` tag; no skip/xfail markers; all 80 PRD citations verbatim-match PRD.md; all test_suite imports resolve against test_helpers exports. Fixed 5 citation wording issues during the verbatim pass.

## Step 6: Generate Implementation — 2026-06-06T05:07:00.000Z

Generated complete Python + Flask in-memory implementation in `workspace/implementation/`. Boots via `start.sh`, binds 0.0.0.0:$PORT, foreground.

**Source files (17):** `start.sh` (foreground, `exec`, guarded pip install), `requirements.txt` (flask 3.0.3), `app.py` (entry, blueprint registration, error handlers), `db.py` (empty-on-boot in-memory `Store`, logical clock, monotonic `_seq`), `errors.py` (ApiError + 20-code catalogue), `response.py` (envelope: `meta`/`response_type`/`data`, `req_` ids, ms-precision UTC), `middleware.py` (`X-User-ID`/`X-User-Role` auth), `util.py` (dt parse, body validators, pagination); `routes/`: participants.py, campaigns.py, catalog.py, pledges.py, events.py; `services/`: calc.py, domain.py.

**Endpoints:** all 38 from PRD §4 implemented and verified registered. Campaign DRAFT→LIVE→CLOSING→{SUCCESSFUL|FAILED}/CANCELED with full cascade (auth replay in created_at/_seq order, captures+surveys or refunds+inventory-release, tier RETIRE) centralized in domain.settle_campaign/cancel_campaign. Parallel Pledge axes tracked independently. Money in integer cents; per-pledge fee Decimal-rounded HALF_UP then summed; reliability HALF_UP to 1dp.

**PRD ambiguities resolved:** (1) Validation precedence on pledge create follows PRD §3.5 prose order; FK resolution before body well-formedness (malformed tier_id/backer_id surface as ERR_FK_INVALID). (2) Multiple queued authorizations — consume most-recently-created authorization; missing → DECLINED. (3) `/_clock/set` never auto-closes; only `/_clock/advance` auto-closes due LIVE campaigns; close+advance require clock ≥ deadline. (4) Add-on attach requires pledge status==ACTIVE and clock < deadline (ERR_CAMPAIGN_NOT_LIVE). (5) settled_amount_cents/goal_met null in DRAFT/LIVE, populated at CLOSING.

## Step 7: Run Tests and Iterate — 2026-06-06T05:14:00.000Z

All 8 parallel rounds pass with 59/59 tests green and zero union failures. The fix is stable and deterministic (the original 3 failures were deterministic precedence bugs, not flaky). Exiting the loop.

**Iterations run:** 2 (initial sweep to surface failures; one fix batch; confirming sweep).

**Root cause:** All 3 failures (deterministic across all 8 rounds) were error-precedence mismatches between two overlapping PRD-defined error codes — `ERR_INVALID_STATE` (generic state-transition gate) vs `ERR_CAMPAIGN_NOT_LIVE` (the live-window temporal gate) — for pledge-create and pledge-cancel.

**Tests deleted:** None. All 3 failing tests passed STEP 1 (PRD verbatim-covers and uniquely determines) and STEP 2 (fixtures/assertions faithful to PRD). The required behaviors were mutually consistent, so these were implementation bugs.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`** (file `workspace/implementation/routes/pledges.py`):
- `create_pledge`: Removed the priority-7 `ERR_INVALID_STATE` state check that pre-empted the temporal gate, and folded the "campaign not LIVE" condition into the temporal gate so it raises `ERR_CAMPAIGN_NOT_LIVE`. PRD §3.5 verbatim assigns "a pledge against a campaign that is not live ... is rejected with `ERR_CAMPAIGN_NOT_LIVE`," making it the unique error for pledging a DRAFT campaign. Fixed `test_not_live_beats_below_tier_min` and `test_pledge_on_draft_campaign_rejected`.
- `cancel_pledge`: Changed the not-LIVE-campaign rejection from `ERR_CAMPAIGN_NOT_LIVE` to `ERR_INVALID_STATE`. PRD §3.5 states cancel is permitted "while the campaign is `LIVE`"; `ERR_CAMPAIGN_NOT_LIVE` is reserved in PRD prose for pledge-create/add-on-attach, so a cancel against a non-LIVE (e.g. SUCCESSFUL) campaign is the generic invalid-state transition. Fixed `test_cancel_captured_pledge_after_close_returns_invalid_state`.

**Final state:** 8/8 parallel rounds green, 59/59 tests passing each round, no flakiness.

## Step 8: Finalize PRD — 2026-06-06T05:38:00.000Z

PRD_FINALIZED.md produced with one minimal, targeted edit.

**Line counts:** PRD.md = 270 lines, PRD_FINALIZED.md = 270 lines. One line revised in place (§3.5, line 146). 0% line-count delta; net +1 sentence + 1 parenthetical within the existing cancel paragraph.

**Changes:**
- §3.5 (pledge cancellation) — revise — pinned the cancel-failure error code: cancelling a pledge is allowed only when the pledge is still `ACTIVE` and the campaign is `LIVE`, otherwise `ERR_INVALID_STATE` (HTTP 409); added a parenthetical clarifying `ERR_CAMPAIGN_NOT_LIVE` is reserved for pledge-create/add-on-attach and not used by cancel — `implementation/routes/pledges.py:230-231, 238-239`.

**Step 7 items mapped:**
- *Fix 1 (create_pledge → ERR_CAMPAIGN_NOT_LIVE for DRAFT/not-live):* No PRD edit. PRD §3.5 already verbatim assigns `ERR_CAMPAIGN_NOT_LIVE` and pins precedence (state → temporal gate). Pure implementation bug, not PRD silence.
- *Fix 2 (cancel_pledge → ERR_INVALID_STATE for not-LIVE):* PRD edit applied. PRD cancel paragraph named no error code; §3.5 precedence prose scoped to pledge *creation* only. Genuine PRD-silence now pinned.

**Pre-edit search:** enumerated cancel_pledge / create_pledge / attach_addon / ship_pledge / campaign lifecycle / settlement cascade; grep confirmed `ERR_CAMPAIGN_NOT_LIVE` appears only in create_pledge and attach_addon. Verified SUCCESSFUL/FAILED/CANCELED post-close states all resolve to `ERR_INVALID_STATE` via cancel route before citing them. Scoped reservation note to "pledge creation and add-on attachment".

## Step 9: Complete PRD — 2026-06-06T05:43:00.000Z

PRD_COMPLETED.md produced. Full PRD-vs-implementation/ scan; all 11 edits in-paragraph, no new sections.

**Source vs completed:** PRD_FINALIZED.md 270 lines / 41,291 chars → PRD_COMPLETED.md 270 lines / 45,158 chars (char delta +3,867).

**Counts:** ambiguity-pins: 10, mismatch-revisions: 1 (total 11 changed passages).

**Per-change bullets:**
- §2.3 Pagination — insert — ambiguity — list ordering tie-break is server insertion order, never `id` — util.py:129/paginate
- §2.7 OCC — insert — ambiguity — absent/non-integer `expected_campaign_version` → `ERR_INVALID_REQUEST` (well-formedness), distinct from stale-version 412 — pledges.py:55-57
- §3.1 Campaign skeleton — insert — ambiguity — campaign-create order: body well-formedness → unknown `creator_id` → `ERR_NOT_FOUND` (404, not FK) → non-owner → `ERR_NOT_OWNER` — campaigns.py:29-45
- §3.5 Pledge create precedence — insert — ambiguity — ownership (`backer_id`==`X-User-ID` → `ERR_NOT_OWNER`) fires after body well-formedness and before state/temporal; not-`LIVE` → `ERR_CAMPAIGN_NOT_LIVE` (also doubles as the 1 mismatch-revision: original list implied a separate `ERR_INVALID_STATE` gate) — pledges.py:60-74
- §3.5 Add-on attach — insert — ambiguity — full attach guard precedence: 404 → addon `ERR_FK_INVALID` → `quantity` `ERR_INVALID_REQUEST` → `ERR_NOT_OWNER` → pledge-not-`ACTIVE` `ERR_INVALID_STATE` → campaign-not-`LIVE` `ERR_CAMPAIGN_NOT_LIVE` → currency → inventory — pledges.py:152-194
- §3.8 Authorization — insert — ambiguity — queue returns created record at 201; multiple queued → most-recently-created (by `created_at`) consumed — pledges.py:328, domain.py:317-324
- §3.8 Clock/close — insert — ambiguity — multiple due campaigns settled ascending `(created_at, insertion order)`; clock endpoints require parseable `now_utc`, return empty data at 200; force-close checks `LIVE`-status before closable-time gate — participants.py:104-106, campaigns.py:146-153
- §3.9 Settlement — insert — ambiguity — pledge with no queued authorization settled exactly as `DECLINED` (→ `AUTH_DECLINED`, excluded from settled total) — domain.py:269-270
- §3.11 Survey complete — insert — ambiguity — guard order (404 → `shipping_address` non-empty string `ERR_INVALID_REQUEST` → `ERR_NOT_OWNER` → readiness `ERR_SURVEY_NOT_READY`); 200 returns updated pledge, not survey — pledges.py:259-283
- §3.11 Ship — insert — ambiguity — non-`SURVEY_COMPLETE` ship → `ERR_INVALID_STATE`; non-owning creator → `ERR_NOT_OWNER` first; 200 returns updated pledge — pledges.py:297-305
- §4 Settlement read — insert — ambiguity — read works for any status: `settled_amount_cents` as stored (`null` pre-close), `captured_pledge_count`/`platform_fee_cents` 0 with no captured pledges, `creator_payout_cents` treats `null` settled as 0 — campaigns.py:178-189

## Pipeline Complete — 2026-06-06T05:43:00.000Z

All 9 steps complete. Final state: 59/59 tests passing across 8/8 parallel stability rounds. Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER designs), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (4 files, 59 tests), workspace/implementation/ (17 source files, 38 endpoints).
