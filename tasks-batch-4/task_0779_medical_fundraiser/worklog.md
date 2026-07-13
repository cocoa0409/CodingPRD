# Worklog — task_0779_medical_fundraiser

## Step 1: Create task directory — 2026-07-06T17:19:38.000Z

Task directory `tasks/task_0779_medical_fundraiser/` was pre-created (index pre-assigned to avoid parallel-task ID contention; Step 1 directory scan skipped per invocation instructions). Created `workspace/` subdirectory. Difficulty: Expert.

## Step 2: Generate scaffold — 2026-07-06T17:45:24.000Z

All three artifacts written and scaffold lint passes clean. Summary:

Domain design — Personal-Cause & Medical Fundraiser (GoFundMe-style), modeled as an event-sourcing + compliance/audit archetype with a flat topology (peer actor entities linked by FKs; TeamMember is a many-to-many Organizer↔Campaign junction) and a parallel state-machine shape (Campaign carries two independent axes). api_prefix: "/".

SCAFFOLD.yaml (§1.0–§1.7):
- 12 entities — Organizer, Beneficiary, Donor, Campaign, TeamMember, Donation, Update, Payout, Dispute, Refund, Hold, FeaturePlacement
- 8 state machines — Campaign(lifecycle), Campaign(payout_posture, computed), Beneficiary(KYC), Donation, Dispute (cyclic UNDER_REVIEW↔NEEDS_INFO), Payout (branching), Hold, FeaturePlacement
- 2 concurrency rules — OCC on Campaign.version for PATCH /campaigns/{id} and POST /payouts (both take expected_campaign_version, bump version)
- 5 calculations — donation_charge_breakdown (fee-on-total gross-up), campaign_available (dual-variant PROVISIONAL/SETTLED + per-donation reserve rounding), entity_risk_score (dual-variant STRICT/LENIENT weighted score), campaign_payout_posture (derived), beneficiary_payout_cooldown
- 20 validations (priority-ordered), 57 endpoints (incl. /_clock/set_current_utc defaulting to 2026-03-01T00:00:00Z), 20 error codes, 6 RBAC roles (Guest, Organizer/Beneficiary/Donor entity-backed, TrustSafetyAgent/PlatformAdmin opaque; peer_roles)

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 18 instances — exactly 2 per each of the 9 Difficulty Rules, each grounded in §1.1–§1.7 with executable setup_api_calls chains and pre-computed literal asserts (e.g. donation total 11875/fee 375; reserve 34 vs naive 33; risk 33 vs 18; dual-variant available 19000 vs 9000).

SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 32 instances — 24 active breadth tests + 8 excluded_because stubs cross-referencing named §1.8 instances.

Lint: clean — all §1.8/§1.9 calls conform to §1.5, all FKs reverse-reachable, no forbidden concurrency vocabulary. No sibling task_*/ directory was read.

## Step 3: Copy INSTRUCTION.md — 2026-07-06T17:45:24.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-06T17:50:53.000Z

Generated workspace/PRD.md — 305 lines — from the medical-fundraiser scaffold (Expert, event-sourcing + compliance-audit task). All 57 endpoints and all 20 error codes represented.

Sections: §1 Introduction (crowdfunding ledger, dual-availability model, logical-clock determinism); §2 Global Specifications (RBAC 6 roles, pagination, common properties + versioning with Update/Refund flagged common_fields:false, precision/fees/reserves, ledger & provisional-vs-settled availability, OCC on both expected_campaign_version endpoints, payout-posture freeze cascade, STRICT/LENIENT risk scoring, validation-priority ordering + logical clock); §3 Business Logic (8 subsections: actor registration & beneficiary verification, campaign lifecycle, team, donations/fees/tax receipts, updates/thank-yous, disputes & refunds w/ 4-level uphold cascade, payout lifecycle incl. deterministic newest-first ON_HOLD sweep, holds & feature placements); §4 endpoint table (57); §5 error table (20).

Hard Contracts all PASS: Contract 1 (field-name coverage, 0 missing), Contract 2 (rule coverage — both OCC rules, all transitions/preconditions/side-effects, all 5 calculations, validation priority, cascades), Contract 3 (§3 path purity, 0 leaks). Confirmed: did NOT read either withheld design YAML.

## Step 5: Generate unit tests — 2026-07-06T18:09:44.000Z

Generated complete test infrastructure under strict design-index-only contract.

test_helpers/ (9 files): types.py (18 enums + 12 entity TypedDicts; Update/Refund as journal entries only id+created_at per §2.4), api_client.py (~55 endpoints), api_errors.py (ApiErrorId enum + HTTP map for all 20 errors), assertions.py (per-entity + assert_campaign_ledger_invariants §2.6), factories.py (payload factories, input fields only), constants.py (calc thresholds), test_users.py (opaque roles as constants; entity-backed roles with make_<role>_headers(id) builders), fixtures.py (primitives + 8 composite scenario bundles), __init__.py.

test_suite/ (conftest + 16 test files, 60 tests): 9 difficulty files test_01–09, corner coverage test_10–16.

Coverage: Queue A (Difficulty) all 18 instances translated, 0 skipped, 2 tests each (36 total). Queue B (Corner) all 24 non-stub instances translated, 0 skipped (1 test each); 8 excluded_because stubs not translated (cross-refs verified resolving to real §1.8 instances). Every test docstring carries exactly one verbatim Design: tag. All 60 tests collect cleanly.

## Step 6: Generate implementation — 2026-07-06T18:09:44.000Z

Generated complete Python + Flask implementation in workspace/implementation/.

Files: app.py (~1000 lines single module — all 12 entities, both Campaign state axes lifecycle+computed payout_posture, beneficiary/dispute/payout/hold/placement state machines, fee gross-up constraint propagation, per-donation-then-summed reserve, dual-variant availability provisional/settled, strict/lenient risk scoring, over-commitment auto-hold cascade, freeze cascades, OCC on expected_campaign_version, payout cooldown, logical clock w/ placement expiry), requirements.txt (flask==3.0.3), start.sh.

Endpoints implemented: 60 (every PRD §4 row). Response envelope meta/response_type/data with error_id/message; auth via X-User-ID/X-User-Role (6 roles); Decimal with ROUND_CEILING/ROUND_HALF_UP for money; campaign money fields/postures computed on read from ledger (no drift); version advanced on direct mutations + 3 declared cascades; validation ordered per §2.10.

Confirmations: start.sh reads $PORT (default 10000), binds 0.0.0.0, guards pip install on flask import, exec's server foreground. Storage in-memory only (module-level DB dicts + logical CLOCK), empty on every boot — no SQLite/disk/seeded data.

Self-check (impl subagent): fee gross-up, per-donation reserve, OCC/precedence, dispute uphold→refund cascade→raised drop→provisional negative→in-flight payout auto-pulled ON_HOLD newest-first, feature-placement half-open overlap, logical clock, verification state machine, posture/version cascades — all pass cleanly with no tracebacks.

## Step 7: Run tests and iterate — 2026-07-06T18:21:49.000Z

All 8 rounds pass cleanly, 60/60 each. Earlier sporadic "errors" confirmed to be host-saturation boot timeouts (vanished at lower peak concurrency via 2-waves-of-4), not real defects.

Iterations run: 2 (baseline sweep → 1 fix → confirming sweep).

Tests deleted: None.

Fixes applied to test_helpers/: None.

Fixes applied to implementation/:
- app.py, function campaign_money: changed paid_out_cents from sum(PAID) - sum(REVERSED) to sum(PAID). A REVERSED payout already leaves the PAID set, so the extra subtraction double-counted, yielding -1000 after reversing the only PAID payout instead of 0.
- app.py, function s_beneficiary: same fix for total_paid_out_cents (sum(PAID) - sum(REVERSED) → sum(PAID)).

PRD basis: PRD §3.7 states settling a payout "adds the amount to the campaign's paid_out_cents" and reversal leaves them "each decremented by the amount" (1000→0). The "with any REVERSED payout's amount subtracted back out" prose describes that net effect, not a second subtraction on top of the payout already dropping out of the PAID set. Failing test test_payout_reverse_decrements_paid_out (asserting paid_out == 0 after reversal) is PRD-faithful; the implementation was the bug.

## Step 8: Finalize PRD — 2026-07-06T18:23:46.000Z

PRD_FINALIZED.md created (305 lines, 0% line delta — 2 in-place inline revisions).

Changes:
- §2.6 (Campaign Ledger) — revise — reworded paid_out_cents from "sum over PAID payouts, with any REVERSED payout's amount subtracted back out" to "sum over payouts currently PAID; a REVERSED payout is out of PAID and contributes nothing, no separate subtraction" — app.py:315
- §2.x (beneficiary fields, line 164) — revise — same reword for total_paid_out_cents — app.py:410

Why: original prose ("subtracted back out") read as a second subtraction of REVERSED amounts on top of the PAID sum — the sum(PAID)-sum(REVERSED) bug Step 7 removed. Impl computes plain sum over currently-PAID payouts in both places; a reversed payout drops out by no longer being PAID. §3.7 "decremented by the amount" left verbatim (accurately describes net effect 1000→0 under sum(PAID)).

## Step 9: Complete PRD — 2026-07-06T18:31:07.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md (305→305 lines, +1215 chars). 6 changes: 5 ambiguity-pins, 1 mismatch-revision.

- §2.7 — revise — mismatch — PRD claimed "a refund posted" advances campaign version; impl's refund_donation never touch()es, so a direct donor refund does NOT advance version (only payout-create, upheld-dispute, settled-payout, hold cascades do). — app.py:947-968 vs 1071,1277,1128,1332
- §2.10 — insert — ambiguity — logical CLOCK used only for cooldown, scheduled_at default, settled_at, placement expiry; created_at/updated_at/api_request_timestamp use wall-clock datetime.now. Clock-set response: empty data object, HTTP 200. — app.py:98-99,135,238,247 / 1056,1117 / 584
- §3.3 — insert — ambiguity — "sufficiently-privileged team member" pinned: pause/resume/complete/cancel/team-add/team-remove/payout require some ACTIVE membership (any team_role); publish/edit require OWNER; removing non-ACTIVE membership → ERR_INVALID_STATE. — app.py:790-831,837-884,880-881
- §3.5 — insert — ambiguity — updates/thank-yous blocked on FROZEN campaign → ERR_CAMPAIGN_FROZEN. — app.py:997-998
- §3.6 — insert — ambiguity — refund endpoint returns newly created Refund record, HTTP 201. — app.py:968
- §3.7 — insert — ambiguity — payout rejects amount_cents <= 0 with ERR_GOAL_INVALID (422), ordered right after beneficiary-verified check. — app.py:1050-1051

## Pipeline complete — 2026-07-06T18:31:07.000Z

All 9 steps done. Final test state: 8/8 stability-sweep rounds pass 60/60. Deliverables present: SCAFFOLD.yaml (+DIFFICULTY/CORNER design), PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (16 files, 60 tests), workspace/implementation/ (app.py, requirements.txt, start.sh), results.{1..8}.json all passing.
