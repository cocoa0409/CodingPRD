# Worklog — task_0041_medical_prior_authorization

Scenario: Medical Prior Authorization Workflow: service/drug pre-approval request, clinical evidence upload, insurance review (Peer-to-Peer), expedited request, denial/Appeal three-tier process, expiration resubmission

## Step 1: Create task directory — 2026-05-29T02:05:29Z

Created `tasks/task_0041_medical_prior_authorization/` and `workspace/` subdirectory. Highest prior index was 0038; user explicitly requested 0041.

## Step 2: Generate scaffold — 2026-05-29T02:23:15Z

Everything checks out. All three files parse, lint is clean, all 9 difficulty rules have exactly 2 instances (18 total), corner design has 33 instances (28 active + 5 stubs), all cross-references resolve, and there are no name collisions.

Generated a complete scaffold for **task_0041_medical_prior_authorization**. All three files written and the scaffold passes `scaffold_lint.py` with `VERDICT: clean lint`.

**Complexity profile:** workflow_orchestration (primary) + compliance_audit (secondary); layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions; **flat** topology; **branching** state-machine shape; **peer_roles**; immediate consistency. Difficulty band: Advanced/upper.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **9 entities:** Provider, Payer, Member, AuthorizationRequest (central), ClinicalEvidence (`common_fields: false`), ReviewDecision, PeerToPeerSession, Reviewer, Appeal. Self-referential FK (`supersedes_request_id`), cross-aggregate links, computed fields (active_authorization_count, sla_due_at, member_cost_share_cents, approved_units, appeal_deadline_at).
- **3 state machines:** AuthorizationRequest (branching + PENDED↔UNDER_REVIEW cycle + EXPIRED→SUPERSEDED), Appeal (three-tier UPHELD→ESCALATED cycle + OVERTURNED/UPHELD fork-join, plus external tier-3), PeerToPeerSession.
- **1 concurrency rule:** OCC CREATE-with-supersede on AuthorizationRequest.version (resubmit-supersede-stale, 412).
- **4 calculations:** sla_due_at (combinatorial mode a), member_cost_share (combinatorial mode b, round-per-line-then-sum; dual-variant cost domain), approved_units_resolution, appeal_deadline (dual-variant compliance-timeline domain).
- **14 validations** (priority-ordered, incl. a 8.5 duplicate-active-auth temporal rule), **35 endpoints** (full CRUD + actions + reverse-reachability GETs + `/_clock/set_current_utc`), **16 error codes**, **4 roles** (Anonymous, Provider, Payer, ExternalReviewer; two entity_backed, two opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 rules × 2 instances = **18 instances**.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **33 instances** (28 active + 5 stubs).

## Step 3: Copy INSTRUCTION.md — 2026-05-29T02:23:32Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-29T02:27:13Z

All three contracts pass. PRD at `workspace/PRD.md`, ~271 lines, 5 top-level sections (Introduction; Global Specifications 2.1–2.10; Business Logic 3.1–3.9; Endpoint Definitions; Error Code Catalogue).

Field coverage: 46/46 present, 0 missing. Rule coverage: all validations/OCC/state-machine transitions/calculations expressed, 0 missing. Path purity §3: 0 path-like tokens. Embedded constants: 72/168 SLA hours, 365-day authorization, 30/30/45 appeal-tier windows, 0.25 expedite factor. Both dual-variant calculations (expedited-vs-standard SLA, expedited-vs-standard appeal window) and per-line-item-before-sum rounding rendered in prose. Confirmed: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate unit tests — 2026-05-29T02:39:57Z

Generated complete test infrastructure for task_0041 (Medical Prior Authorization).

**Stage 1 — `test_helpers/`** (9 files): `types.py` (entity TypedDicts with `ClinicalEvidence` correctly omitting `version`/`updated_at` per `common_fields: false`), `api_client.py`, `api_errors.py` (16 error IDs + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (entity-backed provider/payer header builders + opaque ExternalReviewer/Anonymous constants), `fixtures.py` (composite chains incl. tier-1/2/3 appeal escalation with identity threading).

**Stage 2 — `test_suite/`**: conftest.py + 6 domain test files.

**Counts**: 6 test files, **64 tests total**. Queue A (Difficulty): 36 tests — all 18 instances × 2. Queue B (Corner): 28 tests — all 28 non-stub instances ≥1. **0 instances skipped.** 5 `excluded_because:` corner stubs not translated (as required): calculations/cost_share_full_vs_partial_divergence, calculations/sla_due_at_constants_applied_default_hours, validations/open_p2p_blocks_decision_violation, errors/error_reviewer_payer_mismatch_triggerable, errors/error_p2p_slot_conflict_triggerable. Every test docstring carries verbatim PRD citation + exactly one Design: tag; no skip/xfail markers; all files compile.

## Step 6: Generate implementation — 2026-05-29T02:39:57Z

Generated complete Python + Flask implementation at `workspace/implementation/`.

**Files (8):** start.sh, app.py (routes/auth/RBAC/validation ordering/serializers/error handlers), calculations.py (sla_due_at, member_cost_share per-line-item rounding, appeal_deadline), db.py (in-memory dicts + common-field/version helpers), clock.py (controllable logical UTC clock), errors.py (16-code catalog), response.py (envelope helpers), requirements.txt (Flask only).

**Endpoints: 35** (all from PRD §4 / scaffold §1.5). start.sh confirmed: reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3, in-memory only (no SQLite/file persistence, no startup seeding). One non-state on-disk artifact: `.deps_installed` pip-skip sentinel.

Verified live: payer_id copy-on-create, no-evidence submit block, SLA (168h std / 72h expedited / clock_paused accrual), per-line-item-then-sum rounding, APPROVE/PARTIAL/DENY/PEND transitions, approval cascade to active_authorization_count, 365-day expiry, supersede/resubmit OCC, reviewer-payer mismatch, P2P slot conflict, open-P2P blocks decision, three-tier appeal escalation w/ overturn cascade, expedited appeal window ×0.25, validation priority ordering, pagination, 401/403 enforcement.

## Step 7: Run tests and iterate — 2026-05-29T02:57:29Z

All 8 rounds pass cleanly: 62/62 each (was 64 total; 2 tests deleted). No flakiness. Exiting.

**Iterations run:** 2 (1 baseline + 1 after fixes). Initial state: stable 49/64 across all 8 rounds (no flakiness — same 15 failures every round), clustered into 4 root causes.

**Tests deleted (2):**
- `test_request_status_system_field_input_ignored` (test_01) — DEFAULT/system-field SILENCE + NOT UNIQUELY DERIVABLE. Sent system-managed `status:"APPROVED"` on create and demanded `ERR_VALIDATION`, but PRD never says supplying a non-input/system field must be rejected; §3.9's "wrong type/enum/range" governs declared input fields only. A faithful reader could ignore the field and create a DRAFT. Two divergent faithful implementations exist.
- `test_resume_review_without_new_evidence_rejected` (test_03) — ERROR-ID NOT UNIQUELY DETERMINED. Asserted `ERR_INVALID_STATE` for resuming a PENDED request without new evidence, but PENDED→UNDER_REVIEW is a defined transition and PRD names no error_id for the missing-new-evidence resume path. Positive "resume requires new evidence" rule still exercised by revision-loop tests.

**Fixes to test_suite/ (assertions made more PRD-faithful):** test_01–test_04 — stripped `.000` millis from 11 assertions on `sla_due_at`, `authorization_expires_at`, `appeal_deadline_at`. PRD §2.4 verbatim: these fields "are ISO 8601 UTC values resolved to the second." Implementation was already correct.

**Fixes to implementation/:**
- `db.py` (`DB.next_seq`/`new_common`) — added monotonic `_created_seq` creation-order counter, since the logical clock makes timestamps tie at a pinned instant.
- `app.py` (`render_decision` PEND branch + `resume_review`) — detect "new evidence added after pend decision" (PRD §3.3) by creation sequence rather than clock-equal timestamps; previously evidence added at the same pinned clock instant as the pend was wrongly rejected with `ERR_NO_EVIDENCE`.
- `app.py` (`create_authorization_request` supersede block) — reconciled a PRD internal conflict: §3.9 orders `ERR_INVALID_SUPERSEDE_TARGET` before `ERR_STALE_VERSION`, but §2.10 verbatim governs "another resubmission has already superseded it… flipping it to its superseded state" as `ERR_STALE_VERSION`. Honored the more-specific §2.10 rule; member/provider mismatch still returns `ERR_INVALID_SUPERSEDE_TARGET` first.

**Final:** 8/8 rounds 62/62, zero flakiness.

## Step 8: Finalize PRD — 2026-05-29T03:00:22Z

Produced `workspace/PRD_FINALIZED.md`. PRD.md = 271 lines, PRD_FINALIZED.md = 271 lines. Four lines revised in place (no new sections); ~1.5% modified.

**Changes:**
- §3.2 — revise — request create always yields DRAFT; supplied status/system-managed fields are ignored, not rejected with ERR_VALIDATION — app.py:489.
- §3.3 — revise — resume-review "after the pend decision" judged by creation order (not timestamp); missing new evidence rejected with ERR_NO_EVIDENCE (422) — app.py:584-590, app.py:788, db.py:38-40.
- §3.7 — revise — softened "already superseded → ERR_INVALID_SUPERSEDE_TARGET" to defer to §2.10 carve-out (already-superseded + stale version → ERR_STALE_VERSION) — app.py:467-468.
- §3.9 — revise — added explicit carve-out to supersede-target-before-stale-version ordering: already-superseded + version mismatch → ERR_STALE_VERSION; other invalid-target conditions still fire ERR_INVALID_SUPERSEDE_TARGET first — app.py:456-477.

**No-edit items:** millis stripping (§2.4 already says "resolved to the second", impl already correct — pure assertion fix); db.py _created_seq counter (internal infra, observable effect pinned by §3.3 edit). NO-NEW-MISMATCH pre-edit search performed and logged for all four edits (enumerated all 8 POST create handlers for §3.2; single resume detection site for §3.3; full supersede block for §3.9).

## Step 9: Complete PRD — 2026-05-29T03:03:49Z

Produced `workspace/PRD_COMPLETED.md`. PRD_FINALIZED.md (271 lines, 38,716 chars) → PRD_COMPLETED.md (271 lines, 40,449 chars); +1,733 chars, 0 line-count change (all in-paragraph). **6 ambiguity-pins, 3 mismatch-revisions.**

**Changes:**
- §2.3 Pagination — insert — ambiguity — non-integer limit/offset also rejected with ERR_PAGINATION_INVALID — app.py:122-132.
- §2.3 Pagination — insert — ambiguity — list sort tiebreaker is resource id among equal created_at rows — app.py:147.
- §2.4 Logical Clock — revise — mismatch — logical clock governs persisted timestamp fields only; envelope api_request_timestamp uses real wall clock (PRD said "every time-stamped field") — response.py:31.
- §2.5 Versioning — insert — ambiguity — version initial value pinned to 1 — db.py:43.
- §2.10 OCC — insert — mismatch — omitting expected_authorizationrequest_version on a supersede create yields ERR_STALE_VERSION (412), not ERR_VALIDATION — app.py:461-462,476-477.
- §3.2 — insert — ambiguity — DRAFT initial values: clock_paused_hours/approved_units/member_cost_share_cents = 0; submitted_at/review_started_at/sla_due_at/authorization_expires_at = null — app.py:490-498.
- §3.3 — insert — ambiguity — ReviewDecision row field shape per outcome (APPROVE/PARTIAL/DENY/PEND approved_units, rationale, pend_reason) — app.py:773-775.
- §3.4 SLA Clock — revise — mismatch — clock_paused_hours accumulated/applied as exact fractional hours (sum not rounded to whole hours; displayed to the second); PRD said "whole hours" — calculations.py:27-29, app.py:593-594,904-905.
- §3.7 Expiration — insert — ambiguity — premature expire rejected with ERR_INVALID_STATE (409) — app.py:613-614.

Note: test_helpers/ and test_suite/ live at task root (not under workspace/); cross-reference was implementation-only, which is the alignment target regardless.

---

## PIPELINE COMPLETE — 2026-05-29T03:03:49Z

All 9 steps done. Final state: **62/62 tests passing across 8/8 parallel stability rounds, zero flakiness.** Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (6 files, 64→62 tests), workspace/implementation/ (8 files, 35 endpoints, in-memory Flask).
