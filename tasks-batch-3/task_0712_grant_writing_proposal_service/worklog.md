# Worklog — task_0712_grant_writing_proposal_service

## Step 1: Create Task Directory — 2026-06-29T15:10:36.171Z

Pre-assigned folder used: tasks/task_0712_grant_writing_proposal_service (Step 1 index scan SKIPPED per pipeline pre-assignment). Directory and workspace/ already existed. DIFFICULTY=Expert to be passed to Step 2 scaffold-generator only.

## Step 3: Copy Shared Files — 2026-06-29T15:11:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (done early; independent of scaffold).

## Step 2: Generate Scaffold (design indices only — RESUMED) — 2026-06-29T15:43:16.000Z

RESUME: SCAFFOLD.yaml already existed and was complete (~72KB); only the two test-targeting design index files were missing. Spawned a scaffold-generator subagent that READ the existing SCAFFOLD.yaml (read-only, never modified) and generated the two missing files at Expert difficulty. Orchestrator independently re-validated: both files parse as YAML; DIFFICULTY top-key=scaffold_difficulty_design with 9 rule_ids × 2 = 18 instances; CORNER top-key=scaffold_corner_design with 63 instances; 0 name collisions across the union; SCAFFOLD.yaml unchanged (72291 bytes, mtime 15:19). One unquoted JSONPath `$.data[0].id` flow-mapping value was self-corrected by the subagent before completion.

Subagent summary (verbatim):

Both files are complete and validated. SCAFFOLD.yaml was read only, never modified.

## Summary

I generated exactly the two missing design-index files for `task_0712_grant_writing_proposal_service` at **Expert** difficulty, fully consistent with the existing, untouched `SCAFFOLD.yaml`.

**1. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 Test Targeting Index)**
- **18 instances total**, satisfying the §0.5 rule (≥2 per applicable rule, ≥18 total). Per-rule counts (all = 2):
  - `dual_variant_calc` (invoice_total on Engagement vs match_score on Client — different domains)
  - `combinatorial_formula` (budget_total mode-b rounding-order vs match_score mode-a ≥3-input nonlinear)
  - `non_linear_state_machine` (Proposal revision cycle vs Deliverable parallel axes — different entities)
  - `transitive_cascade` (submission-withdraw depth-3 vs accept-decision depth-2 — different triggers)
  - `priority_pair_validation_conflict` (existence vs owner; state vs temporal — different category pairs)
  - `boundary_precision_check` (ceiling-inclusive on submission create vs zero-report empty-set on award create — different metrics/endpoints)
  - `cross_entity_state_dependency` (Proposal→Engagement vs ComplianceReport→Award — different pairs)
  - `resource_temporal_overlap` (closed-interval billing shared-endpoint reject vs half-open report-window touch-allowed — different semantics/resources)
  - `compensating_invariant` (invoice-void conserves LOGGED minutes vs submission-withdraw conserves proposals_submitted_count — different conserved quantities)

**2. `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9 enumerative breadth)**
- **63 instances total**: 57 active corner instances + 6 `excluded_because` stubs (each citing a real §1.8 instance by name), walking all nine claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross_cutting_complexity_layers, consistency_model).

**Confirmations**
- `scaffold_lint.py` → **VERDICT: clean lint** (711 calls scanned; checks a–f all pass).
- All formula-derived assertions are pre-computed literals (e.g., budget_total=170625, hourly=30000, retainer=516000, success_fee=80000, match_score=75/90/0, win_rate=66.7).
- **All grounds[*] references resolve** to real elements (entity fields, calculations, validation priorities, error_ids, role names, concurrency rule_ids, endpoints, response_envelope) — including strict verification that all 36 state-machine transition refs match real from/to pairs.
- **All 81 instance names are unique** across the union of §1.8 (18) and §1.9 (63) — zero collisions.
- `SCAFFOLD.yaml` was read-only and never modified; no sibling task directories were accessed; no other files were created.

Files:
- `/home/ubuntu/github/CodingPRD/tasks/task_0712_grant_writing_proposal_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0712_grant_writing_proposal_service/SCAFFOLD_CORNER_DESIGN.yaml`

## Step 4: Generate PRD — 2026-06-29T15:50:20.000Z

Spawned a doc-generator subagent reading ONLY SCAFFOLD.yaml (both design indices withheld). Output: workspace/PRD.md (48610 bytes, 297 lines). Subagent confirmed no read of SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml and no sibling-task access.

Subagent summary (verbatim):

All checks complete. The PRD is ready.

## Summary

I generated `/home/ubuntu/github/CodingPRD/tasks/task_0712_grant_writing_proposal_service/workspace/PRD.md` for the Grant-Writing & Proposal Service (domain `grant-writing-proposal-service`, prefix `/grant-desk`).

**Inputs read:** Only `SCAFFOLD.yaml`, the skill `SKILL.md`, the fixed `section-2.2-response-structure.md`, and `example-prd.md` (style reference). I did **not** open, grep, or reference either withheld file (`SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml`), and I did not touch any sibling `task_*/` directory.

**Document structure:**
- §1 Introduction (2 paragraphs)
- §2 Global Specs — 9 domain-derived subsections: RBAC, fixed Response Structure (verbatim), Pagination, Common Resource Properties, Validation Order pipeline, OCC, Cross-Entity Cascades & Derived-Field Reconciliation, Precision/Rounding/Monetary conventions, and The Logical Clock
- §3 Business Logic — 9 lifecycle/process subsections (onboarding & opportunities, engagement & fee model, match scoring, proposal/budget/narrative build, review/revision cycle, proposal review-approval, submission & decision, time & invoicing, post-award compliance)
- §4 endpoint table (4 columns) and §5 error table (2 columns)

**Coverage (all verified mechanically):**
- **Contract 1 (field names):** 72/72 required identifiers present in backticks, 0 missing (initial gap `to_iso8601` fixed).
- **Contract 2 (rule coverage):** spot-checked 16 high-risk rules all PASS — both OCC rejections (with exact error IDs + 412), the deliberately-contrasting closed-interval billing overlap vs half-open report-window overlap, all three invoice variants with pinned rounding order, budget indirect-base computation (EQUIPMENT excluded from base/included in total), match-score weights 50/30/20 + headroom decay, win-rate `0.0` empty boundary, compliance posture GREEN/AT_RISK/DELINQUENT thresholds, report-schedule floor, request-changes APPROVED-deliverable cascade, submission-withdraw proposal cascade, and the explicit 12-step validation priority ordering.
- **Contract 3 (§3 path purity):** 484 §3 backtick tokens, 0 slash-paths, 0 bare HTTP methods, 0 method+path combos.
- **Entities:** all 14 covered. **Endpoints:** all 63 in §4. **Errors:** all 30 in §5 and each also referenced in §2/§3 narrative. **States:** all 38 enum strings present; all 16 enum field values present. §2.2 is byte-identical to the source; no pseudocode operators or fuzzy/approximating words remain in prose.

All three Hard Contracts report PASS.

## Step 6: Generate Implementation — 2026-06-30T03:10:00.000Z

I generated a complete Python + Flask implementation of the Grant-Writing & Proposal Service (Expert-difficulty, 14 entities) in workspace/implementation/.

### Files
- start.sh — guarded pip install (skips when Flask present), exec python3 app.py, foreground.
- app.py — all routes, error handlers, lookup/serialize helpers, invoice variant logic, clock-effect application (~50 KB).
- services.py — calculations and derived-field reconcilers (match score, budget total, win rate, compliance posture, report schedule, interval-overlap math, floor/round-half-up helpers).
- db.py — in-memory dict stores (one per entity), UUID/common-field minting, _seq for stable creation ordering, touch() for version+timestamp bumps.
- clock.py — logical clock (default 2026-03-01T00:00:00Z), ISO-8601 with 3 fractional digits + Z, parser.
- response.py — exact meta/response_type/data envelope; pagination in meta.
- auth.py — X-User-ID/X-User-Role validation, 5-role RBAC.
- helpers.py — pagination parse/validate, body parsing, field/enum/int validators.
- errors.py — ApiError + full 29-entry error->HTTP-status catalogue. requirements.txt — flask.

### Entities (all peer collections under /grant-desk)
Client, FundingOpportunity, Engagement, MatchAssessment, Proposal, BudgetLine, Deliverable, RevisionRequest, Submission, TimeEntry, Invoice, Award, ComplianceReport, BoilerplateSnippet — plus the _clock/set_current_utc test harness endpoint. All 60+ endpoints implemented; storage in-memory only, starts empty (no seeding).

## Step 5: Generate Unit Tests — 2026-06-30T03:22:00.000Z

Generated complete test infrastructure for task_0712 (Grant-Writing & Proposal Service, Expert) from the two design indices only — every test tagged to exactly one instance.

### Stage 1 — test_helpers/ (8 files)
- types.py — 20 status/role enums + 14 entity TypedDicts (full common-field set id/created_at/updated_at/version).
- api_client.py — ApiClient(GenericApiClient) with one method per PRD §4 endpoint (clock + all 14 entity collections, incl. PATCH deliverables).
- api_errors.py — ApiErrorId enum (29 errors) + HTTP_STATUS_CODES map.
- assertions.py — per-entity assert_* shape/invariant checkers.
- factories.py — per-entity payload factories with monotonic unique_ein() helper.
- constants.py — match-score weights, compliance thresholds, clock default, MISSING_UUID.
- test_users.py — opaque-role shared headers + make_client_contact_headers(client_id).
- fixtures.py — composite tiers: setup_drafting_proposal -> setup_review_ready_proposal -> setup_approved_proposal -> setup_filed_submission -> setup_accepted_submission -> setup_active_award, plus setup_engagement_with_time and setup_drafted_deliverable_with_open_revision.

### Stage 2 — test_suite/ (conftest + 5 files, 93 tests)
- test_01_calculations_and_scoring, test_02_state_machines, test_03_cascades_and_compliance, test_04_validations_boundaries_overlap, test_05_entities_endpoints_rbac.

### Coverage audit
- Queue A (Difficulty): 18/18 instances, each with >=2 tests.
- Queue B (Corner): 57/57 non-stub instances, 1 test each; 6 excluded_because stubs not translated.
- Every test docstring carries one verbatim PRD citation + one Design: tag. No skips/xfail, no instances skipped.
- 93 tests collect cleanly under pytest.

## Step 7: Run Tests and Iterate — 2026-06-30T03:42:00.000Z

**Iterations run:** 3 full two-wave 8-round sweeps (initial = 65/93 with 28 stable failures; after helper fix = 89/93 with 4 stable failures; final = 93/93 across all 8 rounds, no flakiness).

**Tests deleted:** None. Every failure traced to a test-side bug (precondition inconsistent with PRD), not PRD silence.

**Fixes applied to test_helpers/:**
- test_helpers/fixtures.py, setup_approved_proposal() — inserted advance_deliverable_content(...) before approve_deliverable(...). The helper created a NARRATIVE deliverable (content_status=OUTLINE) and immediately approved it, but PRD §3.5 requires content_status to be DRAFTED or FINAL when approving from UNREVIEWED (else ERR_NOT_REVIEWABLE). PRD-faithful impl correctly rejected OUTLINE-content approval. This single fix cascaded to 24 of the 28 original failures (all tests transitively depending on setup_approved_proposal / setup_filed_submission / setup_accepted_submission / setup_active_award).

**Fixes applied to test_suite/ (inline test bugs, same root cause — STEP 2 fixture-inconsistency, not implementation):**
- test_01_calculations_and_scoring.py, test_win_rate_two_thirds_rounds_half_up_one_decimal (inner file_and_decide) — added advance_deliverable_content before approve_deliverable (inline OUTLINE-approve).
- test_02_state_machines.py, test_request_changes_resets_approved_deliverable — same inline fix.
- test_04_validations_boundaries_overlap.py, test_stale_proposal_version_on_submission_create — same inline fix.
- test_04_validations_boundaries_overlap.py, test_report_window_touching_endpoint_allowed — changed supplemental window from (2026-09-01, 2026-10-01] to (2027-03-01, 2027-04-01]. Original sat interior to the second scheduled window (2026-09-01, 2027-03-01] and genuinely overlapped under PRD §3.9 half-open rule s1<e2 and s2<e1. Corrected window begins exactly where the last scheduled window ends, so it merely touches (no overlap) — the actual "touching-endpoint-allowed" scenario.

**Fixes applied to implementation/:** None. The implementation was PRD-faithful throughout; all failures were test-side preconditions inconsistent with PRD §3.5 (deliverable approval gate) and §3.9 (report-window overlap rule).

## Step 8: Finalize PRD — 2026-06-30T03:46:00.000Z

Line counts: PRD.md = 297; PRD_FINALIZED.md = 297. Delta: 0 lines (0.0%).
Changes: ZERO edits. Both <step_7_diff> subjects are pure test-fixture bugs where PRD already verbatim-determines the behavior the fixtures violated — no residual PRD silence/ambiguity/mismatch.
- §3.5 deliverable approval gate (root of fixtures.py + 3 inline test fixes): PRD §3.5 line 150 already states UNREVIEWED approval requires content_status DRAFTED/FINAL (else ERR_NOT_REVIEWABLE) + open_revision_count zero. Impl app.py:689-696 matches. No edit.
- §3.9 report-window overlap (root of test_report_window_touching_endpoint_allowed fix): PRD §3.9 line 190 already states half-open windows overlap iff each start strictly before other end; touching endpoints allowed. Impl half_open_overlap s1<e2 and s2<e1 (services.py:249-250). No edit.
PRD_FINALIZED.md is a byte-identical copy of PRD.md — correct outcome given all Step 7 fixes were fixture-side.

## Step 9: Complete PRD — 2026-06-30T03:49:00.000Z

Source (PRD_FINALIZED.md): 297 lines, 48662 chars. PRD_COMPLETED.md: 297 lines, 49032 chars. Char-delta: +370.
Ambiguity-pins: 3. Mismatch-revisions: 0.
- §2.4 Common Resource Properties — insert — ambiguity — pinned version initial value to 1; impl db.py:42 (rec["version"] = 1).
- §3.4 Building the Proposal Budget — insert — ambiguity — pinned amount_cents required as non-negative integer for non-INDIRECT lines; INDIRECT lines do not require it and any supplied value is ignored (derived from rate calc); impl app.py:550-561, services.py:97-100.
- §3.7 Filing the Submission — insert — ambiguity — pinned optional decision_due_utc defaults to null when not supplied; impl app.py:801.
