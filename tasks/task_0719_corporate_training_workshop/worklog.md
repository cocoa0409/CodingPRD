# Worklog — task_0719_corporate_training_workshop

Scenario: Corporate Training & Workshop Delivery: catalog & custom-program design, facilitator & cohort scheduling, virtual/onsite logistics & materials, registration & seat capacity, assessment & certificate/CEU, per-seat vs flat & travel, evaluation/NPS, recurring/enterprise contract

Difficulty: EXPERT (scaffold-generator only)

## Step 1: Create task directory — pre-assigned

Task directory tasks/task_0719_corporate_training_workshop/ and workspace/ pre-existing; index scan skipped per orchestration directive.

## Step 2b: Regenerate design files (subagent) — 2026-06-30T06:04:00.000Z

Both design files regenerated from scratch, grounded purely in SCAFFOLD.yaml §1.1–§1.7 (no sibling tasks consulted). SCAFFOLD.yaml NOT touched.

Files written:
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — single key scaffold_difficulty_design, EXPERT band. 18 difficulty instances total — exactly 2 per §0.5 rule (≥18 required): dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant. All formula-derived asserts computed in Python and pinned as literals (167500/115000, 212000, NPS 67/null, 66.67).
- SCAFFOLD_CORNER_DESIGN.yaml — single key scaffold_corner_design. 45 active + 3 excluded_because stubs across all 9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model). Stubs cite real §1.8 instance names.

One depth-3 difficulty instance rewritten during generation: scaffold's declared `cohort cancel → cert revoke → CEU` cascade is structurally unreachable (cert issuance needs ATTENDED ⇐ RUNNING/DELIVERED, but cancel only valid from OPEN/LOCKED). Replaced with reachable depth-3 `close → FINAL invoice → contract drawdown → EXHAUSTED` chain.

Lint verdict: VERDICT: 2 violation(s), both (f) FK_REVERSE_UNREACHABLE — SessionAssignment.facilitator_id→Facilitator and Evaluation.cohort_id→Cohort. BOTH are scaffold-level (§1.1↔§1.5) checks INDEPENDENT of the two design files (proven: same 2 violations reproduce with empty design files, 0 instances scanned). The two regenerated design files contribute ZERO violations across checks (a)–(e) over all 686 scanned calls. Root cause is a linter segment-derivation heuristic limitation: filtered-list GETs (GET /training/assignments?facilitator_id, GET /training/evaluations?cohort_id) DO exist in SCAFFOLD.yaml §1.5 (reverse-reachability is functionally available), but the linter only infers a collection segment from a GET-by-id endpoint, which SCAFFOLD.yaml lacks for these two. Fixing requires a SCAFFOLD.yaml §1.5 edit, FORBIDDEN by the KEEP-AS-IS hard constraint. Design-file regeneration accepted as clean; 2 pre-existing scaffold-level warnings left as-is per directive.

## Step 3: Copy INSTRUCTION.md (bash) — 2026-06-30T06:06:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0719_corporate_training_workshop/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-06-30T09:23:57.000Z

All checks pass. The §2.2 block is verbatim, 56 endpoint rows match the scaffold's endpoints, 29 error rows match the catalog, and the structure is complete and domain-derived.

## Summary

Generated workspace/PRD.md — a prose PRD for the Corporate Training & Workshop Delivery API (Expert band, quota-allocation primary archetype).

**Structure**
- §1 Introduction: 3 paragraphs framing the dual problem (program design loop + finite seat allocation) and the financial/certification pipeline.
- §2 (10 subsections, domain-derived): RBAC; the fixed verbatim response envelope; pagination; common properties + logical clock (default `2026-03-01T00:00:00Z`, `Evaluation` as the `common_fields:false` exception); seat ledger reconciliation; the 3-level cohort-cancel cascade + contract compensation; OCC on cohort lock; pricing/precision; and validation ordering.
- §3 (9 subsections, lifecycle-organized): program/version authoring loop → facilitators → cohort scheduling/run → sessions+assignments → registration/waitlist → pricing & invoice variants → close/draw-down/NPS → assessment/certificate/revoke → contracts.
- §4: 56-row, 4-column endpoint table. §5: 29-row, 2-column error table.

**Coverage**
- 12 entities, 5 state machines, 5 calculations, 20 validations, 5 roles, 29 errors.
- Role identities translated: 4 opaque (`ProgramDesigner`, `SchedulingCoordinator`, `Learner`, `FinanceManager`) + 1 entity-backed (`Facilitator`).

**Notable design decisions**
- OCC framed purely in stale-version terms; lock-guard ordering stated explicitly (stale-version before min-seats).
- Dual-variant pricing and the PROVISIONAL-vs-FINAL invoice seat-set distinction (CONFIRMED at lock vs ATTENDED-only at close) spelled out; contract reservation (soft hold) vs commitment separated with the no-show delta explained.
- All formulas in precise prose (no operators/fuzzy words): `percent_score` round-half-up to 2dp with boundary-inclusive PASS; NPS promoters ≥9 / detractors ≤6, round-half-up integer, empty→null; budget draw strict `>` with equality allowed.
- Boundary-treatment contrast made explicit (closed-interval room conflict forbidding touching vs half-open facilitator double-booking permitting touching).
- Parameters scattered across ≥2 subsections (e.g., `expected_cohort_version` in §2.7 + §3.3; seat counters in §2.5 + §3.5).

**Hard Contracts** — Field coverage: PASS (65/65). Rule coverage: PASS (0 missing). Path purity (§3 only): PASS (347 tokens scanned, 0 path/method tokens).

## Step 5: Generate Unit Tests (subagent) — 2026-06-30T09:42:00.000Z

All complete. Summary of what was generated.

### Stage 1 — test_helpers/ (9 files)
- types.py — 13 status/role enums + entity TypedDicts. Evaluation correctly omits updated_at/version (common_fields:false); all other entities carry the full common set.
- api_client.py — ApiClient(GenericApiClient), one method per endpoint (clock, programs, versions, facilitators, contracts, cohorts, sessions, assignments, registrations, assessments, certificates, invoices, evaluations).
- api_errors.py — ApiErrorId enum (29 errors) + HTTP-status map, registered via set_error_http_status_map.
- assertions.py — per-entity assertions + assert_seat_ledger_nonnegative, assert_contract_ledger, invoice-total invariant.
- factories.py, constants.py — payload factories + NPS/clock/pagination constants.
- test_users.py — opaque-role shared headers + make_facilitator_headers(id) for the sole entity_backed role (Facilitator) + NO_AUTH_HEADERS for the 401 path.
- fixtures.py — composite tiers: approved version, open cohort, locked-with-confirmed, delivered-with-attendance (drives provisional/final money divergence), running-cohort-one-attendee, onsite-session setup. Facilitator-owned calls thread make_facilitator_headers(fac["id"]).
- __init__.py — barrel export.

### Stage 2 — test_suite/ (conftest + 8 test files, 81 tests)
- test_01_programs_versions.py (12), test_02_cohort_lifecycle.py (15), test_03_registration_seats.py (15), test_04_assessment_certificate.py (7), test_05_invoicing_contracts.py (19), test_06_sessions_overlap.py (5), test_07_nps_evaluation.py (4), test_08_rbac_auth.py (4).

### Coverage (design-index-only)
- Queue A (Difficulty): 36 tests — all 18 instances × ≥2 tests each (verified).
- Queue B (Corner): 45 tests — all 45 non-stub instances × ≥1 test (verified).
- Each test carries exactly one verbatim Design: tag; all 81 tags resolve to real instances; all 81 docstrings carry a verbatim ≥8-word PRD citation (grep-checked against PRD.md).

### Skipped / not translated
- 3 excluded_because: stubs left untranslated as required: error_cohort_lock_stale_version_occ, priority_forbidden_role_over_invalid_state_on_confirm_stub, occ_version_increments_on_every_write_stub. Their difficulty_instance cross-references all resolve to covered queue-A instances.
- No instances failed the PRD-first filter; no skip/xfail/placeholder tests emitted; no scaffold/table references leak into generated code. All files pass py_compile.

## Step 6: Generate Implementation (subagent) — 2026-06-30T09:42:00.000Z

The cleanup succeeded (exit 144 = killed by signal, expected from pkill). All files are in place. The implementation is complete and validated end-to-end.

Generated a complete Python + Flask in-memory REST API at workspace/implementation/.

**Files**
- start.sh — guarded pip install (skips when flask present), exec python3 app.py, binds 0.0.0.0:$PORT (default 10000)
- requirements.txt — flask==3.0.3
- app.py — app factory, blueprint registration under /training, error handlers mapping ApiError/404/405/400/unhandled to the standard error envelope
- db.py — in-memory Store (dicts keyed by id), UUID/req-id/ISO-timestamp helpers, logical clock defaulting to 2026-03-01T00:00:00Z. No seeding.
- errors.py — ApiError class + full 29-entry error catalog with HTTP codes
- response.py — success/created/listing/error envelopes (meta/response_type/data); pagination parse + sort-by-created_at-asc slice
- middleware.py — X-User-ID/X-User-Role auth (401) and RBAC (403)
- common.py — common-fields (created_at/updated_at/version), touch() (version bump), typed body validators, find_or_404
- timeutil.py — ISO 8601 parsing (Z-aware, UTC)
- services.py — seat-ledger recount, waitlist promotion, calculations, cascades, contract settlement
- routes.py — all 58 endpoints

**State machines encoded**: ProgramVersion (DRAFT→IN_REVIEW→APPROVED→SUPERSEDED, request-changes loop, prior-version supersede + active_version_id/PUBLISHED effects); Cohort (SCHEDULED→OPEN→LOCKED→RUNNING→DELIVERED→CLOSED + OPEN/LOCKED→CANCELLED) with four open-preconditions ordered, OCC-before-min-seats on lock, deliver attendance settlement (unmarked CONFIRMED→NO_SHOW), 3-level cancel cascade (registrations→certificates→CEU removal, invoice VOID, reservation release); Registration (WAITLISTED/ENROLLED/CONFIRMED/ATTENDED/NO_SHOW/WITHDRAWN/CANCELLED) with seat-ledger reconciliation and created_at-ASC waitlist promotion on withdraw; Certificate ISSUED→REVOKED with still-valid guard; EnterpriseContract ACTIVE→EXHAUSTED/CLOSED.

**Calculations**: assessment percent_score (ROUND_HALF_UP 2 dp via Decimal, boundary-inclusive PASS); seat_price (per_seat_cents under PER_SEAT, 0 under FLAT); invoice totals (PROVISIONAL over CONFIRMED at lock, FINAL over ATTENDED at close; tuition per pricing model, per-seat materials, travel only for ONSITE/HYBRID; integer cents); contract draw-down (FINAL computed first, strict draw>remaining rejection with FINAL-invoice rollback, EXHAUSTED at exactly 0); cohort NPS (ROUND_HALF_UP integer, null on empty, promoters ≥9 / detractors ≤6).

**Notable decisions**: OCC before min-seats on lock; seat counters always derived by recount (never set directly), cohort version bumped on ledger change; money as integer cents, Decimal only for the two rounding calcs; contract soft reservation tracked as internal _reserved_cents (stripped via _-prefix), does not reduce remaining_cents for close-draw; room conflict closed-interval (adjacency rejected), facilitator double-booking half-open (touching allowed); ERR_COHORT_FULL superseded by waitlist-first prose → full cohort with no waitlist room yields ERR_WAITLIST_FULL; storage purely in-memory, empty on every boot.

## Step 7: Run Tests and Iterate (subagent) — 2026-06-30T10:00:00.000Z

All 8 rounds passed cleanly. The exit condition is met on the first staggered sweep.

## Summary

- Iterations run: 1 sweep (the staggered 2-wave, 8-round protocol). All 8 rounds: passed == total == 81, with 0 failed / 0 errors / 0 skipped in every round.
- Tests deleted: 0. No PRD-silence or non-unique-derivability issues were encountered, because no genuine failures occurred.
- Fixes applied to test_helpers/: 0.
- Fixes applied to test_suite/: 0.
- Fixes applied to implementation/: 0.

The baseline was already clean. The earlier Step-7 sweep's 3 rounds with single "API server ... could not be restarted before <test>" boot-timeout ERRORs (on test_approve_supersedes_prior_version and test_double_submit_rejected) were host-saturation artifacts from launching all 8 servers concurrently — exactly as flagged in the task context. Under the mandated staggered 2-wave protocol (4 concurrent rounds per wave, `sleep 3` between launches, `wait` between waves), those did not reproduce: all 81 tests passed deterministically across all 8 rounds.

The 8 results files (results.1.json … results.8.json) are left on disk at workspace/implementation/.

## Step 8: Finalize PRD — SKIPPED — 2026-06-30T10:01:00.000Z

Skipped per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits, so no PRD_FINALIZED.md is produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD (subagent) — 2026-06-30T10:05:00.000Z

All 7 edits applied as in-paragraph revisions (no new lines, no new sections; line count unchanged at 287). Char delta +1346.

## Summary

**Source vs. completed**: PRD.md 287 lines / 43,817 chars → PRD_COMPLETED.md 287 lines / 45,163 chars (char delta +1,346). No lines added/removed — all changes are in-paragraph inserts/revisions.

**Counts**: ambiguity-pins = 5, mismatch-revisions = 2 (total 7 changes).

**Per-change**:
- §3.5 Registration — revise — mismatch — ERR_COHORT_FULL is described by PRD as a distinct condition but impl never raises it; a full seat pool always routes to the waitlist path and only ERR_WAITLIST_FULL is surfaced when the waitlist is also full — routes.py:646-654
- §3.8 Assessment — insert — ambiguity — PRD's "after delivery" implied a guard, but impl imposes no cohort/registration state precondition on grading; pinned that any registration may be graded in any state — routes.py:744-764
- §3.8 Certificate — insert — ambiguity — PRD silent on the assessment-belongs-to-registration cross-check; pinned that a mismatched assessment_id yields ERR_INVALID_REFERENCE — routes.py:804-805
- §2.3 Pagination — insert — ambiguity — PRD silent on invalid limit/offset; pinned non-integer / out-of-range limit / negative offset → ERR_INVALID_REQUEST (400) — response.py:45-68
- §2.3 Pagination — insert — ambiguity — PRD silent on the created_at tie; pinned the creation-order tiebreaker — response.py:73
- §3.8 Assessment — insert — ambiguity — PRD silent on percent_score serialized shape; pinned whole-number-vs-two-decimal numeric emission (e.g. 80 not 80.00) — services.py:44-52
- §3.1 ProgramVersion — insert — ambiguity (localized §2.9 deviation) — PRD silent on wrong-type program_id; pinned that program_id resolves only against the program table, so a non-program id yields ERR_NOT_FOUND (not ERR_INVALID_REFERENCE) — routes.py:137-139

**Notes on deliberately-unchanged items**: extra additive list filters (status on /assignments, category/status on /programs and /program-versions) are silent in PRD §4 rows but non-contradictory additive behavior, left unpinned. The lock-time soft _reserved_cents hold is tracked but never enforced against later draws (close uses remaining_cents), producing no observable PRD contradiction, left unchanged. results.*.json (all tests passing) used only as auxiliary cross-reference.
