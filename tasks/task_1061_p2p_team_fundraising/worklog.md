# Worklog — task_1061_p2p_team_fundraising

## Step 1: Create task directory — 2026-07-18T00:00:00.000Z

Used pre-assigned directory `tasks/task_1061_p2p_team_fundraising` (no index scan). Created `workspace/`.

## Step 2: Generate scaffold (Expert) — 2026-07-18

13 entities (Organization, Campaign, Event, Team, Participant, Registration, Donor, Donation, MatchPool, IncentiveTier, IncentiveAward, Receipt, Payout); 62 endpoints (incl. `POST /api/_clock/set_current_utc`, default clock `2026-07-01T00:00:00Z`); 35 errors; 6 roles (PlatformAdmin, CampaignManager entity_backed:Organization, FinanceReviewer, Participant, Donor, Anonymous); 11 state machines (Donation carries two parallel dimensions: payment_status × match_status); 10 calculations; 24 validation rows (priorities 1–16); 1 concurrency rule (OCC on `Campaign.version` at `POST /api/campaigns/{id}/payouts`); §1.8 = 18 instances (9 rules × 2); §1.9 = 63 across 9 sections (56 recipes + 7 excluded_because stubs).

Design shape: ledger reconciliation + quota/allocation; flat topology; SoD role model (FinanceReviewer who reviews a payout cannot approve it). Non-linearity: Donation parallel axes, Payout revision cycle (CHANGES_REQUESTED → REQUESTED), Receipt ISSUED → VOIDED → ISSUED, MatchPool EXHAUSTED ↔ ACTIVE. Two depth-4 cascades from different triggers (refund → match reversal → pool restore → pool reactivation; withdraw → registration cancel → count decrement → event reopen). Two conserved quantities (sponsor pool cents; campaign net funds across payout release/void). Two interval semantics: half-open unbuffered match-pool windows vs. closed 90-minute-buffered registration windows.

Verification: all three files yaml.safe_load cleanly; every formula constant has an explicit numeric value (PLATFORM_FEE_PCT 0.05, PROCESSING_FEE_PCT 0.029, PROCESSING_FEE_FIXED_CENTS 30, REFUND_WINDOW_DAYS 60, TRAVEL_BUFFER_MINUTES 90, EARLY_BIRD_DISCOUNT_PCT 0.20, MIN_PAYOUT_CENTS 5000, BASIS_POINTS_SCALE 10000, RECEIPT_NUMBER_PAD_WIDTH 6); all 81 instance names unique; every excluded_because.difficulty_instance resolves; no sibling task read. Lint verdict: clean — all §1.8/§1.9 calls conform to §1.5, all §1.1 FKs reverse-reachable in §1.5 (508 calls scanned).

## Step 3: Copy INSTRUCTION.md — 2026-07-18

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-18

PRD.md = 389 lines. §1 intro → §2 with 11 subsections (RBAC, envelope, pagination, identity/versioning/left-to-right path resolution, logical clock, money & rounding, campaign containment, 16-level validation precedence, OCC, fund conservation identity, derived counters/cascade discipline) → §3 with 10 domain-grouped workflow subsections → §4 endpoint table → §5 error table.

Contract reports: field coverage 91/91 (0 missing); rule coverage — 24/24 validations, 1/1 OCC, 39/39 transitions across 11 machines, 10/10 calculations (incl. both dual-variant pairs FINAL/PROVISIONAL credit and RAW_TOTAL/GOAL_PERCENT leaderboard), 62/62 endpoint side effects, 82/82 entity fields, 8/8 sibling-branch symmetry groups. Path purity check PASS (550 backtick tokens scanned in §3, 0 paths/methods). Coverage: 62/62 endpoints (set-equal to scaffold, no extras), 13 entities, 35 errors, 6 roles. Undeclared constants: NONE — no pre-patching needed. Both design YAMLs left unopened.

## Step 5: Generate unit tests — 2026-07-18

test_helpers/ = 9 files (types.py: 13 entity TypedDicts + 12 status enums; api_client.py: 68 endpoint methods; api_errors.py: 35 error IDs; assertions.py incl. fund/pool conservation invariants; factories.py; constants.py; test_users.py per-instance builders for all 3 entity_backed roles; fixtures.py 5 tiers; __init__.py). test_suite/ = 9 test files + conftest.py, **93 test functions**.

Instance translation: 74 translated, 0 skipped. Queue A 18/18 (≥2 tests each → 36 tests); Queue B 56/56 non-stub (≥1 test each → 57 tests); 7 excluded_because stubs correctly not translated; all difficulty_instance cross-refs machine-verified. AST audit: every one of 93 tests carries exactly one Design: tag resolving to a real non-stub instance; no skip/skipif/xfail; no scaffold reference in emitted code. All ≥40-char PRD citations grep-verified verbatim (0 non-verbatim).

Two assertions trimmed where PRD leaves design space open: (1) leaderboard rows identified by PRD-named `credited_cents`/`goal_percent_bp` rather than un-pinned `team_id`/`participant_id` row fields (RAW_TOTAL↔GOAL_PERCENT inversion still proven); (2) `participant_personal_goal_default_applied_when_omitted` dropped the `team_id == null` assertion (default-value silence). Fixture arithmetic independently verified: fees 153/224/820/7930, nets 1397/2226/9180/92070, report total 377 (round-per-line), match cap 4000, thermometer 150 bp, balances 42070/32070/72070/92070.

## Step 6: Generate implementation — 2026-07-18

workspace/implementation/: start.sh (guarded pip install, exec python3 app.py), requirements.txt, app.py, config.py, db.py (in-memory store + logical clock), errors.py (35 codes), response.py, auth.py, validators.py, routes/ (13 modules), services/calc.py (Decimal/ROUND_HALF_UP cents) + services/domain.py.

Route count 62/62 verified by booting and printing app.url_map (path-for-path match to §1.5); ast.parse passes on all 26 .py files. `bash start.sh` boots and serves on $PORT across 3 kill/relaunch cycles (~0.46s ready), `GET /api/campaigns` → total_count 0 on every fresh boot (no seeding). Behavioral smoke tests 0 failures (fees, cover-fees gross-up, match cap, RCPT-000001 minting, incentives, thermometer/leaderboard inversion, payout SoD cycle + conservation after release and void, refund unwinding, 60-day boundary, buffered registration conflicts, FULL↔OPEN re-derivation, cascades, auth/pagination).

Two PRD ambiguities adjudicated by impl-gen (flagged for Step 7/8/9): (1) §3.1 self-contradicts on post-close registration — took the specific clause (event-CLOSED → ERR_INVALID_STATE checked before the publication gate); (2) strict §2.8 ordering would make ERR_DUPLICATE_REGISTRATION unreachable (buffered-conflict step 9 precedes duplicate step 11 and a same-event repeat self-intersects) — scoped the conflict scan to *other* events, the only reading keeping both errors reachable.

## Step 7: Run tests and iterate — 2026-07-18

All 8 rounds green: 93/93.

**Iterations run:** 2 sweeps (each 8 rounds, 2 waves of 4).

**Sweep 1:** 92/93 in all 8 rounds — one deterministic (non-flaky) failure: `test_02_fundraiser_pages_and_teams.py::test_page_defaults_personal_goal_and_opens_in_pending`, asserting `participant["minimum_met"] is False` on a freshly created page, got `True`.

**Diagnosis:** PRD has two sentences that both bear on `minimum_met`: §3.2 "A new page starts in `PENDING` with `credited_cents`, `projected_cents` and `recruit_count` at 0 and `minimum_met` false." and §2.11 "`minimum_met` is true exactly when `credited_cents` is greater than or equal to the campaign's `fundraising_minimum_cents`, and false otherwise." They only diverge when `fundraising_minimum_cents == 0` (0 >= 0 → true), which is exactly the §3.1 default ("When that minimum is not supplied it defaults to 0") and what the fixture used. The implementation derives the field per §2.11 (`services/domain.py:254`), a faithful PRD reading; so is the literal §3.2 reading. The assertion was therefore not uniquely derivable *as set up* — a fixture artifact, not a real impl bug.

**Fix applied (test_suite/, STEP 2 — fixture made more faithful, assertion preserved):** `test_suite/test_02_fundraiser_pages_and_teams.py` — `test_page_defaults_personal_goal_and_opens_in_pending` now calls `setup_published_campaign(api=api, fundraising_minimum_cents=15000)` instead of the default 0. With a positive minimum both PRD sentences agree that a brand-new page has `minimum_met` false, so the assertion is uniquely determined and was kept intact (not weakened, not deleted). Comment added citing why.

**Tests deleted:** none. **Fixes to test_helpers/:** none. **Fixes to implementation/:** none — the two known impl adjudications (§3.1 post-close registration ordering, §2.8 buffered-conflict scan scoped to other events) produced no failures.

Artifacts: sweep script at `sweep.sh`; results at `workspace/implementation/results.{1..8}.json` (verified 93/93 × 8).

## Step 8: Finalize PRD — 2026-07-18

PRD.md 389 lines → PRD_FINALIZED.md 389 lines (0% line delta; 1 line revised in place).

- §3.2 (Fundraiser Pages, Teams and the Recruiting Graph) — revise — replaced the literal "and `minimum_met` false" on page creation with a statement that `minimum_met` is always derived (per the §3.6 rule) from current `credited_cents` vs the campaign's `fundraising_minimum_cents`, hence false only when that minimum is positive and true when it is 0 — `implementation/services/domain.py:253-254`, surfaced via `ser_participant` at `services/domain.py:344-346`.

Pre-edit search log — (a) subject: the `minimum_met` field on a participant page (initial value, storage, every read path). (b) enumerated: `routes/participants.py:65` (create stores False but responds via ser_participant at :74); `services/domain.py:344-346` (ser_participant refreshes on every serialize); `services/domain.py:241-255` (refresh_participant sets minimum_met = credited >= campaign minimum, 0 when campaign missing); all ser_participant callsites (participants.py:74/81/105/120/156 — every observable read derived, none returns stored False); all refresh_participant cascade callsites (participants.py:73, registrations.py:157, teams.py:90, donations.py:125, campaigns.py:172 — all consistent); registrations.py:159 (confirm-time gate uses the same comparison independently); campaigns.py:26-35 (fundraising_minimum_cents defaults to 0, the exact divergence case); PRD cross-check — minimum_met/fundraising_minimum_cents appear only at lines 117/156/164/186/228, no other sentence asserts an initial false. (c) adjustments: kept "credited_cents, projected_cents and recruit_count at 0" verbatim (genuinely 0 post-recompute); referenced "the §3.6 rule" instead of restating the derivation; said "never stored independently" rather than "not persisted" (the record does hold a field, always overwritten before serialization); scoped the true/false claim to the minimum's sign rather than asserting an unconditional initial value.

## Step 9: Complete PRD — 2026-07-18

PRD_FINALIZED.md 389 lines / 68,287 chars → PRD_COMPLETED.md 389 lines / 76,478 chars (**+8,191 chars, 0 lines**). All edits in-paragraph; no new sections, no new table rows. **29 ambiguity-pins, 5 mismatch-revisions.** Endpoint coverage verified: 62 §4 table rows == 62 route handlers.

Both impl-gen adjudications verified against code and pinned: (1) `routes/registrations.py:79-85` — refresh_event → `if event["status"] == "CLOSED": ERR_INVALID_STATE` runs *before* the PUBLISHED gate; §3.1 revised so the specific clause wins and the general one is scoped. (2) `routes/registrations.py:67-69` — the conflict scan `continue`s on `other["event_id"] == event_id`; §3.3 revised to scope the scan to *other* events with the reachability rationale inline.

Changes (mismatch first):
- §3.1 — revise — mismatch — post-close registration → ERR_INVALID_STATE, event status checked before publication gate — registrations.py:79
- §3.3 — revise — mismatch — buffered-conflict scan excludes same-event registrations; full guard order restated; `minimum_waived` by non-manager → ERR_UNAUTHORIZED — registrations.py:44,64-97
- §2.8 — insert — mismatch — reservation creation runs step 9 ahead of steps 6 and 10 — registrations.py:61-85
- §3.3 — revise — mismatch — confirm checks event state before participant readiness; CLOSED → ERR_INVALID_STATE — registrations.py:146-161
- §3.2 — revise — mismatch — self-recruit clause structurally unreachable; only cross-campaign triggers ERR_SELF_RECRUIT — participants.py:215
- §3.3 — insert — ambiguity — check-in: ERR_PARTICIPANT_NOT_ACTIVE, early check-in → ERR_INVALID_STATE — registrations.py:190-195
- §3.3 — insert — ambiguity — no-show: early → ERR_INVALID_STATE; no ACTIVE-page requirement — registrations.py:207-211
- §3.1 — insert — ambiguity — UNVERIFIED on payout-account → ERR_INVALID_REQUEST; manager reads only its own org — organizations.py:42,52
- §3.1 — insert — ambiguity — campaign create requires organization_id == X-User-ID — campaigns.py:152
- §3.2 — insert — ambiguity — activate: non-PENDING → ERR_INVALID_STATE, before publication gate — participants.py:278-282
- §3.2 — insert — ambiguity — withdraw from WITHDRAWN → ERR_INVALID_STATE; no publication gate — participants.py:293
- §3.2 — insert — ambiguity — a fundraiser may create a team under any PUBLISHED campaign — teams.py:104
- §3.2 — insert — ambiguity — disband: non-ACTIVE → ERR_INVALID_STATE; clears team_id regardless of member status — teams.py:156-161
- §3.5 — insert — ambiguity — closing a CLOSED pool → ERR_INVALID_STATE — match_pools.py:314
- §2.11 — insert — ambiguity — pool allocated_cents derivation and non-CLOSED status re-derivation — domain.py:199-209
- §2.11 — insert — ambiguity — derived counters refresh on read without bumping version/updated_at — domain.py:334-347
- §3.6 — insert — ambiguity — receipt void/reissue preconditions → ERR_INVALID_STATE — receipts.py:148,163-167
- §3.6 — insert — ambiguity — fulfill on non-EARNED → ERR_INVALID_STATE — incentives.py:92
- §3.6 — insert — ambiguity — tiers scanned in created_at order; TEAM/CAMPAIGN gifts create no awards — donations.py:162,169
- §3.6 — insert — ambiguity — FAILED outcome not gated on campaign publication — donations.py:201-207
- §3.8 — insert — ambiguity — leaderboard response_type object, rank (global 1-based), goal_percent_bp on both variants, missing/bad scope → ERR_INVALID_REQUEST — campaigns.py:265-321
- §3.8 — insert — ambiguity — participant scope uses personal_goal_cents, no status filter — campaigns.py:293-298
- §3.7 — insert — ambiguity — refund `reason` validated but not persisted — donations.py:247
- §3.7 — insert — ambiguity — award revocation reached only for PARTICIPANT-designated gifts — donations.py:279
- §2.9 — insert — ambiguity — exhaustive list of campaign-version-advancing operations — payouts.py:288,321,342,359
- §3.10 — insert — ambiguity — a stale payout request supersedes nothing — campaigns.py:403-408
- §3.10 — insert — ambiguity — any reviewer may act on any payout; `note` replaces only when supplied — payouts.py:233-256
- §3.10 — insert — ambiguity — payout single-read is ownership-scoped, list is not — payouts.py:214-230
- §3.10 — insert — ambiguity — payout void `reason` not persisted — payouts.py:350
- §3.9 — insert — ambiguity — manager must own the campaign to read the rollup — campaigns.py:335
- §3.9 — insert — ambiguity — each collection ordered by created_at then truncated to 1000 — campaigns.py:337-352
- §3.4 — insert — ambiguity — CAMPAIGN designation must name the gift's own campaign_id — donations.py:23-25
- §3.4 — insert — ambiguity — Donor-created gifts bind donor_id to X-User-ID; PlatformAdmin does not — donations.py:52-53
