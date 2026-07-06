# Worklog — task_0721_warehouse_club_membership

## Step 1: Create task directory — 2026-06-30T10:34:59.000Z

Used pre-assigned task directory `tasks/task_0721_warehouse_club_membership` as-is (workspace/ already existed). No index scan / auto-increment performed (three sibling pipelines running concurrently).

## Step 2 (finish-only): Generate missing SCAFFOLD_CORNER_DESIGN.yaml — 2026-06-30T10:57:19.000Z

Finish-only re-run of Step 2 (the original Step-2 subagent died at the 600s ceiling before writing the corner index; SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml were already on disk, valid, and were NOT regenerated). A single finish-only subagent read the scaffold-generator skill (§1.9) plus the existing SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml, and generated ONLY tasks/task_0721_warehouse_club_membership/SCAFFOLD_CORNER_DESIGN.yaml at Expert difficulty.

Orchestrator verification (subagent ran async; blocked in-turn on output file): all three SCAFFOLD*.yaml files exist and parse with yaml.safe_load. Top-level keys confirmed — SCAFFOLD.yaml: 13 keys (§1.1–§1.7, no design keys); SCAFFOLD_DIFFICULTY_DESIGN.yaml: [scaffold_difficulty_design]; SCAFFOLD_CORNER_DESIGN.yaml: [scaffold_corner_design] (a list of corner stubs, ~116 KB, 17 excluded_because cross-references citing §1.8 difficulty instances). SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml untouched.

## Step 3: Copy INSTRUCTION.md — 2026-06-30T10:57:19.000Z

Copied ./INSTRUCTION.md → tasks/task_0721_warehouse_club_membership/workspace/INSTRUCTION.md (1424 bytes).

### Step 2 (finish-only) subagent verbatim summary

Generated SCAFFOLD_CORNER_DESIGN.yaml — the §1.9 breadth/enumerative coverage index for the Expert-tier Warehouse-Club Membership scenario. The two existing files (SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml) were not touched.
Stub counts: 86 total corner instances, single top-level key scaffold_corner_design. 69 live instances (full structured test_recipe). 17 excluded_because stubs (no test_recipe), each citing a §1.8 difficulty instance by verbatim name; all 17 resolve to real entries. Examples: discount_stack_pinned_order_instant_then_rebate, cancel_cascade_depth3_fee_ledger_cards, reward_accrual_capped_vs_uncapped_on_membership, no_receipt_lookup_window_inclusive_boundary, state_not_active_beats_member_only_safety.
Breadth dimensions: entities (30), state_machines (18), calculations (13), validations (11), errors (3), rbac (4), cross_cutting_complexity_layers (6), consistency_model (1).
Verification: yaml.safe_load OK, single top-level key; scaffold_lint.py — zero corner-file violations across 69 instances / 467 calls; the 13 reported lint hits are FK_REVERSE_UNREACHABLE scaffold-level checks against pre-existing SCAFFOLD.yaml, not corner-file attributable. All 86 names unique; every live instance has a recipe, every stub omits one.

## Step 4: Generate PRD — 2026-06-30T11:00:58.000Z

Subagent generated workspace/PRD.md (261 lines, 38217 bytes) from SCAFFOLD.yaml only; both design YAMLs withheld. File verified present, non-trivial, and size-stable on disk.

### Step 4 subagent verbatim summary

Generated workspace/PRD.md — 261 lines — Warehouse-Club Membership & Instant Rebate (Expert, pricing-engine + reward-ledger archetype). Sections: §1 Introduction; §2 Global Specs (11 subsections: RBAC 5 roles, Response Structure byte-identical, Pagination, Identifiers/Timestamps/Versioning, Left-to-Right Resolution, Validation Ordering priority 1–13, Money/Precision floor-before-cap, Reward as Conserved Quantity, Fee Accounting, OCC on Membership term, Logical Clock); §3 Business Logic (9 subsections scattering zone); §4 Endpoints (31, 4-col table); §5 Error Catalogue (27, 2-col table). Hard contracts PASS: Field-Name Coverage 60/60, Rule Coverage (both OCC rules, 4 state machines, 6 calculations w/ constants 10000/365/90, 27 errors, cascades), §3 Path Purity 341 tokens 0 violations. No withheld design files or sibling tasks accessed.

## Step 5: Generate Unit Tests — 2026-06-30T11:16:38.000Z

test_helpers/ — 9 files (types.py with common_fields branching; api_client.py 31 endpoints+clock; api_errors.py 27 errors+HTTP map; assertions, factories, constants, test_users entity-backed make_member_headers, fixtures, __init__). test_suite/ — conftest.py + 8 test files, 105 test functions (files 01–04 Difficulty/depth queue, 05–08 Corner/breadth queue). Coverage audited: Queue A all 18 difficulty instances × exactly 2 tests (36); Queue B all 69 non-stub corner instances ≥1 each (~69 tests); 17 excluded_because stubs not translated, all cross-refs resolve; no orphan/dual/untagged tests; every docstring ends with one verbatim Design: line. 0 instances fully skipped. One adjustment: return_refund_receipted_vs_no_receipt_diverge — literal 18000 no-receipt value unreachable (no product-update endpoint), dropped as not uniquely-derivable; kept PRD-derivable facts (receipted 16000, lookup_mode divergence, no-receipt formula member_price*qty, reward claw-back 320 vs 0). All 105 collect; test_helpers imports cleanly; PRD citations verified verbatim.

## Step 6: Generate Implementation — 2026-06-30T11:16:38.000Z

Python+Flask impl at workspace/implementation/. Files: start.sh (foreground; reads $PORT default 10000; binds 0.0.0.0; exec; pip guarded by flask-import check), requirements.txt (Flask), app.py (31 routes + error handlers + auth/RBAC + validation ordering + state machines + calculations), clock.py (logical clock default 2026-03-01T00:00:00Z, never wall-clock), db.py (in-memory store + id/timestamp/version stamping), errors.py, response.py, middleware.py, helpers.py, services.py, serializers.py. Storage: pure in-memory dicts (one per entity), no disk/SQLite/seeding; wiped on each fresh process; fresh boot total_count:0. All 31 endpoints implemented. Smoke-verified: envelope/req_ ids/ISO-8601 UTC 3-digit/auth 401/RBAC 403/ownership scoping; pinned instant→rebate pricing with clamp; executive reward floored-then-capped; dual-variant refunds block rounding; redemption on renewal w/ counter reset & over-redeem 422; OCC renew/cancel 412; validation priority (OCC before state, state 409); cancel proration; clock-driven lapse→EXPIRED cascade card REVOKE; no-receipt 90-day window boundary; error paths. start.sh confirmed reads $PORT/binds 0.0.0.0/foreground/HTTP 200.

## Step 7: Run Tests and Iterate — 2026-06-30T11:37:47.000Z

Sweep shape: two waves of four (host-saturation guard), 8 rounds total, --isolation per-test-server, --start-command kept the `cd ... && bash start.sh` prefix.

Iterations run: 2 (initial sweep diagnosed; one fix batch → all-green sweep).

Tests deleted: None.

Fixes applied to test_helpers/:
- fixtures.py — create_pending_membership: changed the signup signer from TEST_USERS["member_headers"] (role Member) to ADMIN (ClubAdmin). PRD endpoint table authorizes POST /memberships to Anonymous, ClubAdmin only; a prospective signer is not yet a Member, so the impl correctly returned 403 first (§2.6 authorization precedes everything). This single upstream fixture bug caused 80 of the 84 setup failures.

Fixes applied to test_suite/:
- test_05_entities_crud.py — 5 direct api.create_membership(..., MEMBER) signup calls switched to ADMIN (same PRD signer rule; Member cannot sign up). Also test_membership_version_increments_on_renew: changed version == 2 to version == ver + 1 — PRD §3.3 says renewal "increments the version by one," and activation is itself a mutation that bumps version (§2.4/§2.8), so a hardcoded 2 mistranslated the rule.
- test_08_security_concurrency_misc.py — test_occ_renew_correct_version_succeeds: same version == 2 → version == ver + 1 fix.
- test_07_calculations_corner.py — test_payment_redemption_reduces_renewal_fee: STEP 1c partial-coverage split. Kept PRD §3.8-covered assertions (one REDEMPTION ledger entry, amount_cents == -800); removed the post-renewal reward_redeemed_cents == 800 assertion, which contradicts §3.3's "resets reward_redeemed_cents to 0 for the new term."
- test_02_lifecycle_and_cascades.py — test_cancel_cascade_revokes_card_and_fees: changed precondition from a basic/no-reward membership to an executive plan with a reward-bearing finalized transaction so unredeemed reward exists for cancel's EXPIRY entry to zero. PRD §2.8 states EXPIRY ledger entries "are negative," so a faithful impl writes EXPIRY only when unredeemed reward > 0; original setup had zero reward, making the >= 1 EXPIRY assertion unsatisfiable. annual_fee kept at 6000 with zero redeemed reward preserves CANCEL_REFUND == -6000.

Fixes applied to implementation/: None — the implementation was PRD-faithful throughout; every failure traced to test/fixture identity or assertion bugs.

Final sweep: all 8 rounds passed == total, 105/105 each round.

## Step 8: Finalize PRD — 2026-06-30T11:40:52.000Z

Produced workspace/PRD_FINALIZED.md (cp of PRD.md + minimal patch). PRD.md=261 lines; PRD_FINALIZED.md=261 lines (1 line revised in place; ~0% line-delta).

Changes:
- §2.8 (Reward as a Conserved Quantity) — revise — added that an EXPIRY ledger entry is written only when unredeemed reward (reward_accrued_cents − reward_redeemed_cents) is strictly positive, and none is written when there is nothing to expire — implementation/services.py:126-130 (_expire_unredeemed_reward). Boundary scoped to the four EXPIRY-writing paths (manual renew, auto-renew, lapse, cancel); reinstatement-via-RENEWAL-on-EXPIRED deliberately excluded (writes no EXPIRY).

Items verified already PRD-determined (NOT edited): activation increments version (renew yields ver+1, §2.4 + §3.3; test's ==2 was a test bug); post-renewal reset of reward_redeemed_cents to 0 (§3.3 verbatim); signup signer must be Anonymous/ClubAdmin (§2.1 + §4 table; Member 403 was a fixture bug).

## Step 9: Complete PRD — 2026-06-30T11:45:34.000Z

Produced workspace/PRD_COMPLETED.md (cp of PRD_FINALIZED.md + full-impl-scan minimal patch). PRD_FINALIZED.md=261 lines/38,630 chars; PRD_COMPLETED.md=261 lines/41,741 chars (char delta +3,111; all in-paragraph, 0 sections added). 13 changes: 8 ambiguity-pins, 5 mismatch-revisions. (test_helpers/test_suite exist; implementation/ was the alignment target.)

Changes:
- §2.2 insert(amb): api_request_id format (20 random alphanumeric) + api_request_timestamp from logical clock — response.py:12,20
- §2.2 revise(mis): api_request_timestamp = logical clock not wall-clock — response.py:20
- §2.3 insert(amb): offset min 0/no upper bound/empty page; non-integer pagination → ERR_INVALID_PAGINATION — helpers.py:44-52
- §2.3 insert(amb): list sort tiebreak ascending id — helpers.py:71
- §2.4 insert(amb): id = UUIDv4 lowercase hyphenated; created_at/updated_at/*_utc stamped from logical clock — db.py:7-17,34-51
- §2.10 revise(mis): renew/cancel apply pending clock-driven boundary transition before version check — app.py:259,314
- §3.2 insert(amb): plan_id existence resolved before body well-formedness; primary_member_name non-empty — app.py:198-199
- §3.2 revise(mis): redemption only on RENEWAL payments; SIGNUP ignores redeem_reward_cents — app.py:369-377
- §3.2 insert(amb): reinstatement FeeEvent amount; SUCCEEDED RENEWAL on ACTIVE = no-op-but-recording — app.py:396-415
- §3.3 revise(mis): auto-renew qualifier "any SUCCEEDED RENEWAL payment, not term-scoped" + full-fee FeeEvent + term roll + reward-counter reset — services.py:92-106,118-123
- §3.4 insert(amb): cardholder_name non-empty; card add needs no ACTIVE membership; ADDON FeeEvent term_start null while PENDING_PAYMENT — app.py:436-477
- §3.5 insert(amb): ERR_MEMBER_ONLY_PRODUCT practically unreachable (state check first); per-member-limit counts all OPEN txn lines + current-term FINALIZED lines — app.py:748-761,704-727
- §3.7 insert(amb): receipted-creation w/ no matching line (purchased=0 → ERR_RETURN_QTY_EXCEEDS_PURCHASED); approval non-FINALIZED original → ERR_TRANSACTION_NOT_OPEN; line attributable-accrual reconstruction (block-round proration) — app.py:926-933,1028-1029,880-904
Left unchanged: no-receipt "most recent qualifying transaction" ordering has no observable effect (impl records only lookup_mode string).
