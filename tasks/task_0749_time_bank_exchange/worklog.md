# Worklog — task_0749_time_bank_exchange

## Step 1: Create task directory — 2026-07-04T00:00:00.000Z

Task directory `tasks/task_0749_time_bank_exchange/workspace` prepared (pre-allocated by caller).

## Step 2: Generate scaffold — 2026-07-04T18:46:00.000Z

result: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml written to /home/ubuntu/github/CodingPRD/tasks/task_0749_time_bank_exchange/ at Expert difficulty; `scaffold_lint.py` VERDICT: clean lint.

Scaffold summary
- Domain: time-bank-exchange (Expert; ledger_reconciliation + multi_party_negotiation; flat topology; cyclic state machines; peer_roles; immediate consistency)
- §1.1 Entities (12): Member, SkillOffer, SkillRequest, Exchange, LedgerEntry, Redemption, VerificationCredential, GroupProject, ProjectShift, ShiftAssignment, Dispute, ImpactReport
- §1.2 State machines (9): Exchange (branching+cyclic DELIVERED↔DISPUTED), SkillRequest (branching w/ auto-expire), VerificationCredential (cyclic SUBMITTED↔REVISION_REQUESTED), GroupProject (compound aggregate_state), ProjectShift, ShiftAssignment (auto NO_SHOW), Dispute, Redemption, SkillOffer
- §1.2.1 Concurrency rules (1): redemption-stale-member-version (OCC on Member.version at POST /redemptions)
- §1.3 Calculations (8): chronological_balance, forward_looking_balance (variants), trust_tier (tiered selection), no_show_strikes (rolling 90d window), project_aggregate_state, project_completion_ratio, report_top_skill, report_hours_exchanged (variants, SUM_ORDER pinned)
- §1.4 Validations (14, priority-ordered) — auth → existence → state → OCC → ownership → suspend → balance → shift-overlap → exchange-overlap-with-buffer → offer/request-state → trust-tier → verifier-eligibility → request-shape
- §1.5 Endpoints (58): CRUD + action for members, offers, requests, exchanges, ledger-entries, redemptions, credentials, group-projects, shifts, assignments, disputes, impact-reports, plus test-driving `/_clock/set_current_utc` and `/_ledger/admin-adjust`. All FKs have reverse-reachability.
- §1.6 Error catalog (13): auth (401/403), 404, state (409), OCC (412), safety (403), fiscal (402), overlap (409x2), trust (403), verifier (403), request shape (400)
- §1.7 RBAC (4 roles): Anonymous, Member (entity_backed), ProjectOrganizer (entity_backed), PlatformAdmin (opaque)

§1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml): 9 rules × 2 instances = 18 total. Per-rule breakdown:
- dual_variant_calc: 2 (forward_vs_chronological_balance on Member, gross_vs_net_hours on ImpactReport)
- combinatorial_formula: 2 (mode-b nested rounding, mode-a tiered selection)
- non_linear_state_machine: 2 (Exchange DELIVERED↔DISPUTED cycle, VerificationCredential SUBMITTED↔REVISION cycle)
- transitive_cascade: 2 (project-cancel depth-3, clock-advance-noshow depth-3, different triggers)
- priority_pair_validation_conflict: 2 (safety vs fiscal, state/OCC vs referential/ownership)
- boundary_precision_check: 2 (balance `>=` on POST /exchanges, ratio `>=` on POST /_clock via GroupProject)
- cross_entity_state_dependency: 2 (Exchange↔Dispute, Exchange↔SkillOffer/Member.trust_tier)
- resource_temporal_overlap: 2 (ShiftAssignment half-open touching-allowed, Exchange 30-min buffer)
- compensating_invariant: 2 (chronological_balance conservation on exchange-cancel round-trip, no_show_strikes conservation on assignment-cancel round-trip)

§1.9 (SCAFFOLD_CORNER_DESIGN.yaml): 41 instances across 9 sections (33 active + 8 excluded_because stubs pointing to §1.8):
- entities: 11
- state_machines: 6
- calculations: 6
- validations: 5
- endpoints: 2
- errors: 2
- rbac: 2
- cross_cutting_complexity_layers: 6 (OCC positive/negative, cascading, dual-variant, derived-field, pagination)
- consistency_model: 1

`scaffold_lint.py` VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. (58 endpoints, 12 entities, 18 §1.8 instances, 33 §1.9 instances, 401 calls scanned.)

## Step 3: Copy INSTRUCTION.md — 2026-07-04T18:47:00.000Z

Copied `INSTRUCTION.md` from project root to `tasks/task_0749_time_bank_exchange/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-04T18:53:00.000Z

PRD is complete at 272 lines. All three Hard Contracts audit clean.

result: PRD written to /home/ubuntu/github/CodingPRD/tasks/task_0749_time_bank_exchange/workspace/PRD.md (272 lines) — Time-Bank Exchange API PRD with §1 introduction, §2.1 RBAC (all 4 roles with identity translation), §2.2 verbatim envelope, §2.3 pagination, §2.4 common resource properties + all enum vocabularies, §2.5 logical clock and lazy time-gated sweeps, §2.6 ledger integrity + chronological/forward-looking balance variants, §2.7 trust tier ladder, §2.8 OCC on `Member.version` with `expected_member_version` + `ERR_STALE_MEMBER_VERSION` 412, §2.9 compound state + cascades, §2.10 precision and rounding (per-exchange-then-sum), §2.11 priority-ordered validation (all 14 rules with error IDs), §3.1 onboarding + peer verification, §3.2 offers/requests, §3.3 booking/delivery/settle/cancel, §3.4 disputes + reduced-credit path, §3.5 group projects + shift cascade + no-show cascade, §3.6 redemptions + fulfil/void, §3.7 impact reporting (with pinned tie-break) + admin adjust, §4 4-column endpoint table (58 rows), §5 2-column error table (13 rows).

Audit results:
- Contract 1 (Field-Name Coverage): entities 65/65 present, endpoint-inputs 50/50 present, 0 missing — PASS
- Contract 2 (Rule Coverage): walked all 14 priority-ordered validations, the 1 concurrency rule, ~35 state transitions across 9 machines, 8 calculations (with the two variants and the SUM_ORDER pinning), all cross-entity cascades (project cancel → shift → assignment; third NO_SHOW → is_suspended; settlement → both balances + provider trust_tier), sibling branches (DISPUTED→DELIVERED via reject/withdraw and DISPUTED→SETTLED via uphold rendered with equal density; VERIFIED/REJECTED/REVISION_REQUESTED from both SUBMITTED and REVISION_REQUESTED), and every endpoint side-effect — 0 missing — PASS
- Contract 3 (§3 Path Purity): 357 backtick tokens scanned in §3; 0 slash-prefixed, 0 bare-HTTP-method, 0 method+path combined — PASS

Line count: 272.

## Step 5: Generate unit tests — 2026-07-04T19:18:00.000Z

All files present, all tests parse, all 64 citations verify against PRD (whitespace/backtick/bold normalized), all design tags resolve to real instances, all stub cross-refs resolve.

result: Generated 64 tests across 11 test files + 9 test_helpers modules for task_0749_time_bank_exchange.

**Helpers modules (9):** `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**Test files (11 + conftest, 64 tests total):**
- `test_01_member_lifecycle.py` — 7 tests
- `test_02_skill_offer_and_request.py` — 3 tests
- `test_03_exchange_lifecycle.py` — 6 tests
- `test_04_ledger_and_balances.py` — 5 tests
- `test_05_validations_and_auth.py` — 6 tests
- `test_06_boundary_and_temporal.py` — 5 tests
- `test_07_disputes_and_state_cycles.py` — 5 tests
- `test_08_projects_and_shifts.py` — 5 tests
- `test_09_redemptions_and_occ.py` — 5 tests
- `test_10_impact_reports.py` — 5 tests
- `test_11_difficulty_complements.py` — 12 tests

**Coverage vs design indices:**
- Difficulty (queue A): 16/18 instances × 2 tests each = 32 tests emitted.
- Corner (queue B): 32/33 non-stub instances × 1 test each = 32 tests emitted.

**Skips (3 total, all PRD-first two-condition filter failures):**
1. `Difficulty/combinatorial_formula/trust_tier_tiered_selection_mode_a` — SKIPPED (circular bootstrap: TRUSTED verifier required for peer verification, no PRD path to reach TRUSTED without one).
2. `Difficulty/non_linear_state_machine/credential_submitted_revision_submitted_cycle` — SKIPPED (same bootstrap gap for `request-revision` trust_tier requirement).
3. `Corner/endpoints/fk_reverse_reachability_offer_by_member_id` — SKIPPED (C2 violation: PRD does not name member_id as a filter on GET /skill-offers).

## Step 6: Generate implementation — 2026-07-04T19:29:00.000Z

- **Modules (13 files):** `app.py`, `db.py`, `errors.py`, `response.py`, `auth.py`, `requirements.txt`, `start.sh`, `services/{validators,balance,ledger,pagination,clock_sweep,projects,reward_catalog,serializers}.py`, `routes/{clock,members,skill_offers,skill_requests,exchanges,ledger,redemptions,credentials,group_projects,shifts,assignments,disputes,impact_reports}.py`
- **Endpoints:** 55 routes across 13 blueprints (all endpoints in SCAFFOLD.yaml §1.5 covered)
- **LOC estimate:** ~1900 lines
- **Storage:** in-memory Python dicts keyed by UUID; empty at boot; no seeding
- **Smoke test:** boot <30ms once flask installed; verified member registration, admin ledger seeding, offer/request/exchange creation, mark-delivered, settle-with-ledger-posting, OCC 412 on stale version, insufficient-balance 402, trust-tier-too-low 403, unauth 401, role-not-permitted 403
- **Self-audit result:** all 22 output-checklist items pass

result: Implementation complete at workspace/implementation/ — Python + Flask, 13 modules, 55 endpoints, in-memory dicts, guarded start.sh.

## Step 7: Test and iterate — 2026-07-04T19:35:00.000Z

All 8 rounds passing 64/64. Sanity check: the sweep is the 8-round parallel per-test-server run described in the prompt, all 8 results.json exist and each reports passed==total==64.

result: All 8 parallel rounds pass 64/64 after removing an over-eager submission-time subject!=verifier check in workspace/implementation/routes/credentials.py.

Summary:
- Iterations run: 2 (initial sweep + one fix + confirming sweep).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`:
  - `/home/ubuntu/github/CodingPRD/tasks/task_0749_time_bank_exchange/workspace/implementation/routes/credentials.py` — `create_credential`: removed the submission-time `subject_id == verifier_id` -> `ERR_OWNERSHIP_VIOLATION` guard. PRD §2.7/§2.9 pins the subject-not-verifier gate to verify/reject/request-revision only (returning `ERR_VERIFIER_INELIGIBLE`); rejecting the same-subject-and-verifier tuple at POST /credentials was added-behavior not traceable to PRD, and it blocked the setup phase of `test_self_verify_rejected_with_verifier_ineligible` which deliberately creates a self-verifier credential to exercise the verify-time gate.

## Step 8: Finalize PRD — 2026-07-04T19:38:00.000Z

result: PRD_FINALIZED.md created as byte-identical copy of PRD.md; the single Step 7 diff item (removal of submission-time subject==verifier guard in routes/credentials.py) was an impl-side fix aligning to PRD text — no PRD silence or PRD/impl mismatch remains, so no PRD edits were required.

- **Line counts**: PRD.md = 272, PRD_FINALIZED.md = 272, delta = 0 lines, 0% change.
- **Per-item outcome**: `routes/credentials.py:19` (`create_credential`) — no edit — Step 7 removed an added-behavior guard that had no basis in PRD.md; §2.7/§2.11/§3.1 already scope the subject-not-verifier gate to verify/reject/request-revision. Fixture/impl-fix category, not PRD-silence or PRD-mismatch.
- **Per-edit pre-edit search log**: 0 edits; subject enumerated across `create_credential`, `_verifier_gate`, `verify_credential`, `reject_credential`, `request_revision`, `resubmit`, `services/balance.py:50`, `services/serializers.py:110-111`. All consistent with PRD as-written.

## Step 9: Complete PRD — 2026-07-04T19:48:00.000Z

result: PRD_COMPLETED.md written to workspace/PRD_COMPLETED.md — 9 minimal inline edits pin implementation-observed behavior across §2.10, §2.11, §3.1, §3.3, §3.4, §3.5, §3.6, and §3.7.

- Source: PRD_FINALIZED.md — 272 lines, 49366 chars.
- Target: PRD_COMPLETED.md — 272 lines, 51784 chars (+2418, +0 lines).
- Ambiguity-pins: 6. Mismatch-revisions: 3.

Changes:
- §2.10 Precision and Rounding — revise — ambiguity — pinned `delta_minutes` for admin-adjust must be nonzero (0 rejected as `ERR_INVALID_REQUEST`) — services/validators.py:57-60
- §2.11 Suspension, Safety Gates — insert — ambiguity — `is_suspended` sticky, never reset by strike recompute — services/balance.py:97-100
- §3.1 Trust ladder / credential submission — insert — ambiguity — acting `X-User-ID == subject_member_id`; subject-not-verifier + tier gates only at verify/reject/request-revision — routes/credentials.py:46-47
- §3.3 Booking an Exchange — insert — ambiguity — only the requester may create the exchange; else `ERR_OWNERSHIP_VIOLATION` — routes/exchanges.py:54-55
- §3.4 Disputes — revise — ambiguity — `claimed_delta_minutes` closed range [15, 480]; acting member must equal `raised_by_member_id` — routes/disputes.py:26, 37-38
- §3.4 Disputes UPHELD path — insert — mismatch — on UPHELD, linked `SkillRequest` also transitions `MATCHED → CLOSED` — routes/disputes.py:130-134
- §3.5 Group Projects shift creation — revise — mismatch — shifts creatable while `aggregate_state ∈ {PLANNING, OPEN}`; `shift_start_utc` in closed `[window_start_utc, window_end_utc]` — routes/group_projects.py:158-159, 170-171
- §3.5 Publishing / assignment gate — insert — mismatch — strict `>` on `window_start_utc` for publish; self-assign requires `aggregate_state ∈ {OPEN, IN_PROGRESS}` else `ERR_INVALID_STATE` — routes/group_projects.py:90-91; routes/shifts.py:77-79
- §3.6 Redemptions — insert — ambiguity — reward-catalog resolution: fixed roster plus trailing-`_<positive int>` fallback; unresolvable codes → `ERR_INVALID_REQUEST` — services/reward_catalog.py:27-42
- §3.7 Impact Reports / top_skill_code — revise — ambiguity — per-exchange `skill_code` from linked `SkillOffer.skill_code`; `top_skill_code` `null` when no settled exchanges; tie-break considers only ledger entries with `entry_kind ∈ {EARNED, SPENT, DISPUTE_REVERSAL}` whose linked offer's `skill_code` is among still-tied codes — routes/impact_reports.py:82-89, 91-92, 105-125
