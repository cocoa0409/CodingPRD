# Worklog — task_0788_digital_legacy_planning

## Step 1: Create task directory — 2026-07-07T10:59:35.000Z

Pre-assigned folder `tasks/task_0788_digital_legacy_planning` used as-is (workspace/ already present). Step 1 index scan skipped per run instructions (ID pre-assigned to avoid contention with parallel runs).

## Step 2: Generate scaffold (Expert) — 2026-07-07T11:29:00.000Z

All checks pass. The scaffold for task_0788 is complete and validated.

Generated three files:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

`scaffold_lint.py` reports VERDICT: clean lint across all 297 §1.8/§1.9 calls, and every §1.1 FK has reverse-reachability in §1.5. All three parse as valid YAML; every computed assert literal (refund 800, completeness 66, NET allocation 5000/3000/1999, GROSS 10000, net_value 4800) was verified by executing the formulas.

Design shape (Expert): flat topology under `/legacy`, access-control-matrix + multi-party-negotiation archetypes, layers = optimistic_concurrency / cascading_side_effects / dual_variant_calculation / scheduled_deferred_actions; 3 roles (Owner→entity_backed:Plan, Deputy→entity_backed:Deputy, PlatformAdmin→opaque); logical clock default 2026-03-01T00:00:00Z.

Counts:
- Entities: 10 (Plan, VaultItem, Deputy, Beneficiary, Directive, ReleaseRequest, Subscription, Share, Integration, ReviewReminder)
- Endpoints: 51 (includes `/_clock/set_current_utc` and `/_ops/run-review-sweep`)
- State machines: 10
- Error codes: 27 (plus 1 concurrency_rule: OCC on Plan.version via directive activate)
- §1.8 depth instances: 18 (9 rule_ids × 2)
- §1.9 corner instances: 26 (23 active test recipes + 3 `excluded_because` stubs)

All 44 instance names unique. Post-check: yaml.safe_load OK on all three files.

## Step 3: Copy shared files — 2026-07-07T11:30:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-07T11:35:00.000Z

All three contracts (field coverage, rule coverage, path purity §3) PASS.
- PRD line count: 271 (on-disk 270)
- Endpoints documented: 51 (matches scaffold endpoint_count: 51) ✓ race-check passed
- Entities documented: 10 (all with id/created_at/updated_at/version)
- Errors catalogued: 27; roles: 3 (Owner, Deputy, PlatformAdmin)
- Calculations: plan_completeness_pct, subscription_refund (2 variants), beneficiary_allocation (floor-then-waterfall by created_at), seat_accounting, release_quorum (ceil*0.5 floor 1), next_review_due (30-day grace)
- Confirmed: SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were NOT read.

## Step 5: Generate unit tests — 2026-07-07T11:52:00.000Z

Stage 1 — test_helpers/ (9 files): types, api_client (51 endpoint methods), api_errors (27 IDs + HTTP status map), assertions, factories, constants, test_users (Owner/Deputy entity-backed + opaque PlatformAdmin), fixtures (composites: setup_release_approved, setup_released_asset, setup_release_verified_multi_deputy, setup_plus_plan_completeness_66, setup_activated_directive), __init__ barrel.

Stage 2 — test_suite/ (7 test files + conftest): 57 test functions, all collect cleanly.
- Difficulty queue (A): 17 of 18 instances covered, 2 tests each = 34.
- Corner queue (B): all 23 non-stub instances covered, 1 test each = 23.

Instances skipped (1):
- validation-priority precedence not uniquely derivable — Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_share. Asserts ERR_SHARE_WINDOW_OVERLAP wins over ERR_SEAT_LIMIT_REACHED, but PRD §3.7 lists seat-limit before overlap and §2.8 ordering only covers auth→…→state core; not uniquely derivable. Sibling state_beats_fiscal_on_grant kept (§2.8 orders state check 6th/core).

Adjudication: Corner/errors/grant_before_quorum_returns_quorum_not_met kept but isolated (added sealed in-scope item + non-past-due subscription so only quorum check fires).
Every docstring carries exactly one Design: tag (57=57). No skip/xfail markers.

## Step 6: Generate implementation — 2026-07-07T11:52:00.000Z

Source files (6): app.py (51 routes), domain.py (calculations + serializers), helpers.py (auth/RBAC/scope/validation/pagination), store.py (in-memory dicts, logical clock default 2026-03-01T00:00:00Z), errors.py (ApiError + 27-code HTTP status catalog), plus requirements.txt + start.sh.

Endpoint count: 51 (49 under /legacy + /_clock/set_current_utc + /_ops/run-review-sweep).
start.sh: reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py, pip install guarded behind flask-import check.
Storage: in-memory dicts only, no seeding. Fresh boot returns empty collections.

Key interpretation decisions: ownership scope enforced on Owner reads + mutations (§2.1); share creation checks ERR_SUBSCRIPTION_REQUIRED before seat-limit; entity-specific 404 codes; directive activation on non-ACTIVE plan returns ERR_INVALID_STATE (state precondition before OCC).

## Step 7: Test-fix iteration loop — 2026-07-07T11:58:00.000Z

All 8 rounds pass 57/57. Clean sweep achieved. (Ran 8 rounds as 2 waves of 4 to avoid host saturation.)

Iterations run: 2 (1 diagnostic sweep + 1 verification sweep after fixes).

Tests deleted: None. All three failures were test-artifact bugs, not PRD-silence.

Fixes applied to test_suite/ (all in test_07_access_control.py — per-test setup/assertion fixes, not implementation weakenings):
1. test_get_nonexistent_plan_returns_not_found — assertion relaxation (permitted one-of exception). PRD §2.8 says existence checks return ERR_NOT_FOUND but also defines entity-specific codes like ERR_PLAN_NOT_FOUND used where a specific referenced resource is missing. GET on missing plan is exactly that case → not uniquely determined (STEP 1b). Changed validate_error(resp, ERR_NOT_FOUND) → validate_error_is_one_of(resp, [ERR_NOT_FOUND, ERR_PLAN_NOT_FOUND]). Impl returns ERR_PLAN_NOT_FOUND (PRD-valid).
2. test_deputy_creating_vault_item_unauthorized — setup precondition fix (STEP 2). Setup created a seat-consuming deputy on a plan with no subscription. PRD §2.9: seat_limit treated as 0 when plan has no subscription, so impl correctly rejected with ERR_SEAT_LIMIT_REACHED. Added create_subscription(api, plan_id, tier="PLUS") before deputy creation. Assertion (ERR_UNAUTHORIZED) unchanged.
3. test_deputy_reading_unreleased_item_rejected — same setup precondition fix (STEP 2). Added PLUS subscription before create_and_accept_deputy. Assertion (ERR_ACCESS_NOT_RELEASED) unchanged.

Fixes applied to test_helpers/: None (added already-exported validate_error_is_one_of and create_subscription to test_07's import line).

Fixes applied to implementation/: None — implementation was already PRD-faithful on all three points.

FINAL: 57/57 across all 8 rounds.

## Step 8: Finalize PRD — 2026-07-07T12:02:00.000Z

Produced workspace/PRD_FINALIZED.md. One edit applied.

Line counts: PRD.md = 270, PRD_FINALIZED.md = 270 (0% delta; single sentence revised in place in §2.8).

Change:
- §2.8 (existence check / not-found code) — revise — Pinned which not-found code the existence check returns: entities with a defined specific code (Plan, VaultItem, Deputy, ReleaseRequest, Directive, Subscription, Share) return that entity-specific code for both path ids and body FKs; entities without one (Beneficiary, Integration, ReviewReminder) return generic ERR_NOT_FOUND. Traces to Step 7 diff item #1 (GET missing plan → ERR_PLAN_NOT_FOUND). Impl: domain.py:33-101.

Items not requiring edit: Step 7 diff #2, #3 are fixture-only precondition fixes (missing PLUS subscription); impl behavior (seat_limit=0 with no subscription → ERR_SEAT_LIMIT_REACHED) already pinned in PRD §2.9.

## Step 9: Complete PRD — 2026-07-07T12:08:00.000Z

Produced workspace/PRD_COMPLETED.md via full PRD-vs-implementation scan.

Source vs completed: PRD_FINALIZED.md 270 lines / 38,775 chars → PRD_COMPLETED.md 270 lines / 40,759 chars (+1,984 chars). 5 ambiguity-pins, 3 mismatch-revisions (8 changes).

Changes:
- §2.3 Pagination — insert — ambiguity — list ties on identical created_at break by ascending insertion sequence, never by id (helpers.py:200).
- §2.5 Logical Clock — insert — ambiguity — ops endpoint bodies: set-clock returns 200 empty data object (app.py:1050); run-review-sweep returns the plan resource (app.py:1090).
- §2.8 Validation Ordering — revise — mismatch — ERR_CROSS_PLAN_REFERENCE fires only on share + beneficiary creation, not release-request (requested_by_deputy_id binds to acting deputy; foreign plan caught by scope gate as ERR_FORBIDDEN_SCOPE) (app.py:581-604,415-418,838).
- §2.9 Seat Accounting — revise — ambiguity — no uniqueness enforced; most-recently-created subscription governs tier/seat-limit/refund/gating (domain.py:105-109).
- §3.6 Release filing — insert — mismatch — filing only checks deputy serves the plan, no ACCEPTED re-check (app.py:582-590).
- §3.6 Release voting — revise — mismatch — voting doesn't re-check ACCEPTED; deputy appended to approver_deputy_ids on every vote, approval_count incremented only on APPROVE (app.py:657-676).
- §3.6 Grant precedence — insert — ambiguity — grant guards state-first: ERR_QUORUM_NOT_MET/ERR_INVALID_STATE precede sealed-items + past-due checks; ERR_NOTHING_TO_RELEASE precedes ERR_SUBSCRIPTION_PAST_DUE (app.py:696-712).
- §3.7 Record-payment — revise — ambiguity — CANCELED subscription rejects any outcome with ERR_INVALID_STATE; SUCCEEDED accepted from any non-CANCELED status; FAILED accepted only from ACTIVE (app.py:800-814).

## Pipeline complete — 2026-07-07T12:08:00.000Z

All 9 steps done. Final: 57/57 tests pass across all 8 stability rounds. Outputs: SCAFFOLD.yaml + 2 design files, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ + test_suite/ (57 tests), workspace/implementation/ (Flask, in-memory).
