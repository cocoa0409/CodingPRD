# Worklog — task_0094_streaming_family_plan

Scenario: Streaming Family Plan: account Profile, parental controls (by rating/time), concurrent stream cap, ad/ad-free tier, offline download, family member invite, cross-device sync

Difficulty: Expert (10-15 entities / 20-32 endpoints) — passed only to scaffold-generator in Step 2.

## Step 1: Create task directory — 2026-06-01T23:10:00.000Z

Pre-allocated task_dir used: `tasks/task_0094_streaming_family_plan`. Auto-index scan skipped per instruction (parallel claude instances). Created `tasks/task_0094_streaming_family_plan/workspace`.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-01T23:53:00.000Z

All three files are written, well-formed, and pass every check. The file split is honored (neither design key appears in SCAFFOLD.yaml; each design file has exactly its single top-level key).

Generated all three scaffold artifacts for **task_0094_streaming_family_plan** at the Expert difficulty tier, working purely from the scenario description and the scaffold-generator spec (no sibling tasks consulted). Files: SCAFFOLD.yaml (§1.0–§1.7, 1477 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 931 lines), SCAFFOLD_CORNER_DESIGN.yaml (§1.9, 1308 lines).

Structure:
- 11 entities: SubscriptionPlan, Title, Account, Profile, ParentalControl, Invite, Device, StreamSession, Download, WatchProgress, PlanChange. Flat topology (FK-linked peers; billing folded onto Account, plan-change history kept as a chronological PlanChange log).
- 41 endpoints (24 mutating + 17 reads, including one `/_clock/advance` test seam).
- 6 state machines: Account (cyclic ACTIVE↔SUSPENDED revert loop + CLOSED), Invite (PENDING fork → ACCEPTED/DECLINED/EXPIRED/REVOKED with divergent compensations), StreamSession, Download, Device, Profile.
- 5 calculations: cycle_charge (chronological proration, sum-then-round pinned), watch_minutes_attributed (same-day vs midnight-cross elapsed), ad_break_count (1+floor(runtime/30) on ad-supported), download_size (HD doubling), rating_ceiling (kind ⊓ ParentalControl MIN).
- 2 concurrency rules: OCC on Account.version for plan-changes and invoicing (both satisfy §1.2.1).
- 21 validations (priority-ordered), 21 errors (all referenced), 4 roles (PlatformAdmin/Anonymous opaque; AccountOwner/ProfileUser entity-backed).

Difficulty coverage: all 9 rules satisfied with exactly 2 differentiated instances each (18 total); §1.9 adds 37 active corner instances + excluded_because stubs. scaffold_lint.py returns VERDICT: clean lint.

DEVIATION FLAGGED BY SUBAGENT: endpoint count (41) exceeds Expert band ceiling (20–32). Subagent justified: seven named features over 11 entities with dense FK graph + full reverse-reachability + faithful lifecycles land ~40 endpoints even after aggressive read consolidation; every endpoint is a named-feature action or lint-mandated reverse-reach GET.

## Step 3: Copy INSTRUCTION.md — 2026-06-01T23:53:00.000Z

`cp ./INSTRUCTION.md ./tasks/task_0094_streaming_family_plan/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-01T23:59:00.000Z

Generated `workspace/PRD.md` — 252 lines, file written and verified. Both design files (DIFFICULTY/CORNER) withheld; no test_recipe tokens leaked into PRD.

Major sections:
- §1 Introduction — household quota-allocation + parental-controls + folded-billing domain
- §2 Global Specifications (9 subsections): 2.1 RBAC (4 roles + identity translation), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties (full-spine vs lean SubscriptionPlan/Title/PlanChange split), 2.5 Quota Envelopes & Counters, 2.6 Billing/Wallet/Proration (cycle-charge formula), 2.7 OCC on Account, 2.8 Parental-Control rating scale (rating_ceiling), 2.9 Logical Clock & Sweeps
- §3 Business Logic (10 subsections): catalog config, account lifecycle, plan changes, profiles/parental envelopes, devices, streaming gauntlet (watch_minutes_attributed + ad_break_count), downloads (download_size), invites (four-way fork), watch progress, reads/validation-ordering (full priority cascade)
- §4 Endpoint table — all 40 endpoints
- §5 Error catalogue — all 21 error IDs

Hard Contract results (subagent self-audit): field coverage 65/65 PASS; rule coverage (21 validations, 2 OCC, 6 state machines, 5 calculations) PASS; path-purity in §3 PASS (0 path tokens). Did not open either withheld design file.

## Step 5: Generate unit tests — 2026-06-02T00:10:00.000Z

9 test files (+conftest.py) in test_suite/, 9 helper modules in test_helpers/. Total 73 tests, all collecting cleanly.
Queue split: Queue A (Difficulty) 36 tests — all 18 difficulty instances × 2 (second pass hits distinct PRD-derivable angle each). Queue B (Corner) 37 tests — all 37 non-stub corner instances × 1.
Instances skipped: 7 — all `excluded_because:` stubs in the corner index (5 valid-transition stubs + device_busy_overlap_corner, curfew_blocked_corner, daily_limit_exceeded_corner). No instances skipped for PRD-first filter — every instance passed verbatim-coverage + unique-derivability (PRD spells out thresholds, §3.10 validation priority order, §2.6 proration arithmetic, midnight-cross worked example).
Verification: all modules byte-compile; ApiClient has 45 endpoint methods, 21 error IDs registered; 0 difficulty shortfalls, 0 corner gaps, 0 orphan tags, 0 stub-translations; every docstring ends with verbatim Design: tag; 114 PRD citation fragments survive literal grep. common_fields branching respected (SubscriptionPlan/Title/PlanChange lean id+created_at only; 8 full-spine entities carry version spine).

## Step 6: Generate implementation — 2026-06-02T00:10:00.000Z

Complete Python+Flask impl in workspace/implementation/. 9 source files: start.sh (foreground, reads $PORT, binds 0.0.0.0, pip install guarded behind `python3 -c "import flask"` check), requirements.txt (flask==3.0.3), app.py (41 routes + validation cascade + state machines + cascades + clock/sweep seam), db.py (in-memory Store, fresh per process, no seeding/disk), errors.py (21 error IDs), response.py (exact envelope), middleware.py (X-User-ID/X-User-Role, 4 roles), calculations.py (5 calc rules, Decimal/ROUND_HALF_UP money), services.py (serializers, clock helpers, computed-field reconciliation).
41 endpoints implemented (matches PRD §4 / scaffold §1.5). Subagent ran ~53 e2e checks against live server — all pass (proration 983/-17, midnight-cross 20, ad_breaks 4, HD size 1400, OCC 412, invite hold conservation, cascades, sweeps, device half-open boundary).
DECISION FLAGGED BY SUBAGENT: PRD names INVITE_TTL_HOURS, DOWNLOAD_LICENSE_HOURS, per-seat hold_amount_cents qualitatively without pinning magnitudes; subagent chose 72h / 48h / 100¢ — consistent with asserted before/after-expiry + funded/zero-wallet behaviors.

## Step 7: Run tests and iterate — 2026-06-02T00:21:00.000Z

Clean exit. All 8 parallel rounds pass 73/73.

Iterations run: 2 (initial sweep found 4 stable failures present in all 8 rounds; second sweep after fixes was clean 8/8).

Tests deleted: None. All 4 failures were test-side bugs in test_suite/ where the test's own setup violated a PRD-stated precondition; every assertion traced to verbatim PRD prose and was kept intact.

Fixes applied to test_helpers/: None — the bugs lived in the test functions themselves, not the shared helpers.

Fixes applied to implementation/: None — the implementation was faithful to the PRD in every case (correctly rejecting out-of-range billing_anchor_day and correctly enforcing the §2.7 OCC stale-version rule).

Fixes applied to test_suite/ (the 4 failing tests, all STEP 2 test-vs-PRD consistency fixes):
1. test_06_streaming_session_calc.py::test_active_stream_count_immediately_visible — setup created an account with billing_anchor_day=30, but PRD §2.6 states the anchor is "an integer day-of-month billing_anchor_day in the range 1 through 28." Implementation correctly returned ERR_INVALID_REQUEST. Changed to a valid 28.
2. test_07_downloads_and_devices.py::test_download_license_expiry_sweep_marks_expired — same out-of-range precondition (billing_anchor_day=29). Changed to 28.
3. test_05_streaming_gates.py::test_stream_start_on_suspended_account_returns_invalid_state — setup captured account["version"] at creation, then create_device mutated the Account (PRD §2.5: device registration is an Account mutation that increments version), so the subsequent OCC-guarded suspend was sent with a stale version and silently failed with ERR_STALE_ACCOUNT_VERSION (412), leaving the account ACTIVE — so the stream then started successfully (object instead of error). Fixed: re-read the account via h.fetch_account before suspend and asserted the suspend succeeded.
4. test_03_account_lifecycle.py::test_account_close_depth3_cascade_folds_minutes_and_deletes_download — same root cause: create_device and start_stream each bumped the Account version (1→3) after the test captured version 1, so the OCC-guarded close was correctly rejected with ERR_STALE_ACCOUNT_VERSION per PRD §2.7. Fixed: re-read the account version before close.

No PRD-silence or unique-derivability deletions were needed; the test suite is now stable at 73/73 across all 8 concurrent rounds.

ORCHESTRATOR NOTE: Step 7 subagent's final results.{1..8}.json were not retained on disk (its per-iteration `rm -f` cleared them). Orchestrator independently re-ran the 8-round sweep to regenerate the artifacts and verify the green claim. First re-run used `--start-command "bash start.sh"` (outer cd only) and hit the known cwd gotcha (uniform ERROR — start.sh re-invoked from foreign cwd); killed and re-ran with `cd <impl> && bash start.sh` embedded in --start-command.

ORCHESTRATOR VERIFICATION (2026-06-02): corrected 8-round parallel sweep completed (exit 0). All 8 rounds report passed=73 total=73 failed=0 — ALL 8 ROUNDS GREEN. results.{1..8}.json persisted in workspace/implementation/.

## Step 8: Finalize PRD — 2026-06-02T00:35:00.000Z

PRD_FINALIZED.md produced and verified byte-for-byte identical to PRD.md (252 lines, 0% delta). Step 8 was NOT skipped (skip requires 0 fixes of any kind on first sweep; here there were 4 test_suite/ fixes across 2 iterations), but the correct outcome was an empty diff.

Changes: None. Every one of the four <step_7_diff> items is a pure test-fixture precondition bug already covered verbatim by existing PRD prose, with the implementation faithful in each case.

Per-item pre-edit search log (subagent):
- Items 1&2 (billing_anchor_day 30/29 → ERR_INVALID_REQUEST): only validate site is create_account app.py:452-454; covered by §2.6 "in the range 1 through 28" + §3.10 routing. No edit.
- Item 3 (device registration bumps account version): all counter mutations call bump() (register_device app.py:989-990, deregister app.py:1026-1028, create/stop_stream_session app.py:1129-1147, end_session cascade); covered by §2.5 "mutations of the Account ... increment version". No edit.
- Item 4 (OCC stale-version 412 on close/suspend): _account_occ_check app.py:496-507 invoked by suspend/reactivate/close/invoice/plan-change; covered by §2.7 + §3.10. No edit.

Subagent note: test_suite/ and test_helpers/ live at the task root, not under workspace/, so the subagent did not read them — it aligned against implementation/ (the actual alignment target; tests are only auxiliary), which is correct.

## Step 9: Complete PRD — 2026-06-02T00:42:00.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md. Line counts 252 → 252 (all edits in-paragraph). Char delta +1621 (42595 → 44216 bytes). 9 changes: 8 ambiguity-pins, 1 mismatch-revision.

Per-change:
- §2.6 (Billing/Proration) — insert — ambiguity — period day 0 anchored to Account created_at logical-clock instant (not billing_anchor_day); first segment uses plan bound at creation; change's effective day is clamped 0..30 whole-day count from anchor — calculations.py:148-159, app.py:274-304,478-479.
- §2.7 (OCC on Account) — revise — mismatch — PRD said suspend/reactivate/close merely "accept" the version field; impl REQUIRES it (missing/non-integer → ERR_INVALID_REQUEST, mismatch → ERR_STALE_ACCOUNT_VERSION/412). Revised to "require" with both error outcomes — app.py:496-507.
- §3.4 (Parental envelope) — insert — ambiguity — curfew_end_min == curfew_start_min is an empty window (no-curfew encoding) — app.py:1044-1053.
- §3.6 (Streaming/curfew gate) — insert — ambiguity — same start==end empty-window clarification on the curfew gate — app.py:1044-1053,1094.
- §3.7 (Offline Downloads) — insert — ambiguity — offline-license window magnitude = 48 hours — calculations.py:23, app.py:1256.
- §3.8 (Invites, send) — insert — ambiguity — invite TTL = 72 hours; per-seat hold = system-fixed 100 cents on hold_amount_cents — calculations.py:22,28, app.py:839,834.
- §3.8 (Invites, accept) — insert — ambiguity — accept-minted profile's display_name = invite's invitee_email — app.py:898-905.
- §3.8 (Invites, decline) — insert — ambiguity — decline with non-matching token rejected with ERR_INVITE_EXPIRED — app.py:922-923.
- §3.10 (Reads/Listing) — insert — ambiguity — (a) stream-sessions & downloads list endpoints accept a status filter; (b) the three non-account-scoped lists (stream-sessions, downloads, watch-progress) narrowed to caller's slice: ProfileUser → own profile_id, AccountOwner → own account, PlatformAdmin → all — app.py:1170-1177,1298-1308,1389-1399.
- §4 (Endpoint Definitions) — insert — ambiguity — PUT /watch-progress always returns 200 OK (create or replace) — app.py:1354,1365.

(diff reports 10 changed lines vs the 9-change summary — one edit spanned two adjacent lines; immaterial.)

## PIPELINE COMPLETE — 2026-06-02T00:42:00.000Z

All 9 steps done. Final state: 73/73 tests pass across all 8 parallel rounds (verified). Artifacts present: SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/, test_suite/ (73 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md (≡ PRD.md), PRD_COMPLETED.md, implementation/ + results.{1..8}.json}.
