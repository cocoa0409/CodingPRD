# Worklog — task_0172_provider_credentialing

## Step 1: Create task directory — 2026-06-05T13:40:31.000Z

Created `tasks/task_0172_provider_credentialing/` and `tasks/task_0172_provider_credentialing/workspace/` via `mkdir -p`.

## Step 2: Generate scaffold — 2026-06-05T14:09:57.000Z

All three scaffold artifacts are generated and validated. Final lint verdict: clean.

Generated the Expert-level scaffold for **Provider Credentialing & Enrollment**:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile:** primary archetype compliance/audit, secondary multi-party negotiation (peer-review committee); layers = derived-field reconciliation, rate/threshold triggers, optimistic concurrency, scheduled actions; hybrid topology; posture-driven state shape (layered with a cyclic re-credentialing loop and branching fork-join review); segregation-of-duties role model; immediate consistency.

**Counts:**
- Entities: 11 (CredentialingOrg, Payer, SanctionsSource, Provider, CredentialItem, VerificationRequest, SanctionsScreening, CredentialingFile, PeerReviewer, PeerReviewVote, PayerEnrollment)
- State machines: 6 transition blocks across 5 entities (Provider has two — linear intake + cyclic re-cred loop; CredentialItem branching-with-revert; CredentialingFile fork-join; SanctionsScreening; PayerEnrollment) + 1 concurrency rule (OCC on CredentialingFile.version)
- Calculations: 7 (expirable_band, credentialing_readiness_score, credentialing_posture, recredentialing_due_date [dual-variant], enrollment_effective_date [dual-variant], peer_review_tally, sanction_score)
- Validations: 18 (ordered, includes two business_temporal interval-overlap rules)
- Endpoints: 49 (lean action surface; the bulk are mandatory single-resource GETs and reverse-reachability list endpoints across 11 entities in a flat/hybrid topology)
- Errors: 35
- Roles: 6 (SystemAdmin, CredentialingSpecialist, MedicalDirector, PeerReviewer, EnrollmentCoordinator, ComplianceOfficer)

**Design instances:** §1.8 difficulty = 9 rule_ids × 2 = 18 instances (all nine §0.5 rules satisfied with differentiation). §1.9 corner = 9 sections, 39 active instances + 3 `excluded_because` stubs.

**Validation:** `scaffold_lint.py` → `VERDICT: clean lint`. No forbidden concurrency vocabulary, no design-key leakage into SCAFFOLD.yaml, every error code referenced, all stub references resolve, all instance names unique across both files, all formula-derived asserts precomputed as literals. No sibling tasks inspected.

## Step 3: Copy shared files — 2026-06-05T14:10:12.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0172_provider_credentialing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-05T14:15:31.000Z

All checks pass. The PRD is complete and verified.

**Output:** `workspace/PRD.md` (~323 lines, 46 KB)

**Document metrics:**
- 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue)
- 17 subsections: §2 has 10 domain-derived cross-cutting subsections (RBAC, response structure, pagination, common properties, nested retrieval, validation ordering, deterministic clock, expirable banding, precision, OCC); §3 has 7 lifecycle/process subsections (org setup, application lifecycle, credential verification, sanctions, peer review, payer enrollment, re-credentialing cycle)

**Hard Contracts — all PASS:** field coverage (59/59 entity fields, 38/38 request bodies, all query params), rule coverage (17 validations ordered in §2.6, 1 OCC rule, all state machine transitions, 7 calculations reconstructible, sibling-branch symmetry), path purity (§3 has 0 path/method tokens). §5 catalogue contains all 35 scaffold error IDs; §4 table lists all 49 endpoints.

**Confirmation:** Did NOT read either `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`. Read only SKILL.md, SCAFFOLD.yaml, section-2.2-response-structure.md, and example-prd.md.

> NOTE: A first attempt at Steps 5 & 6 was interrupted by a session limit; the prior subagents' writes did not persist to disk (test_helpers/, test_suite/, workspace/implementation/ were all absent on resume). Steps 5 & 6 were re-run fresh and concurrently. The records below are from the successful re-run.

## Step 5: Generate unit tests — 2026-06-05T18:02:31.000Z

Generated complete test infrastructure for `task_0172_provider_credentialing`.

**Test files: 7** (plus `conftest.py`), **75 tests total**, all collected cleanly by pytest against the real framework.

- `test_01_provider_intake.py` (13) — org defaults, provider/credential-item/payer creation, required/typed fields, not-found, application lifecycle preconditions
- `test_02_verification_and_sanctions.py` (6) — verification completion, reverify revert loop + fresh-request cascade, lapsed-credential block, screening resolution
- `test_03_calculations.py` (9) — expirable-band boundary, readiness score (full/two-thirds/capped), peer-review tally chair-double-on-tie, recred-due rolling variant, enrollment effective-date dual variant
- `test_04_peer_review.py` (11) — file lifecycle, voting guards (duplicate/segregation/referential), quorum boundary, outcome-match, OCC stale-version, fork-join approve/deny branches
- `test_05_enrollment_and_cascades.py` (15) — enrollment lifecycle, panel capacity, cross-entity gates, depth-2/depth-3 cascades, compensating invariants, recred cyclic loop, clock-driven demotion, temporal-overlap rules
- `test_06_listing_and_rbac.py` (5) — reverse-reachability listings, RBAC (403/401)
- `test_07_difficulty_reinforcement.py` (16) — mandatory second test per difficulty instance, each asserting a distinct PRD-derivable observable

**Queue provenance:**
- Queue A (Difficulty): all **18** instances covered, each by exactly **2 tests** (36 tests) — meets the ≥2 requirement.
- Queue B (Corner): all **39 non-stub** instances covered by ≥1 test (39 tests).
- **Skipped: 3** instances — all `errors`-section `excluded_because` stubs (`error_provider_not_cleared_already_covered`, `error_credential_interval_overlap_already_covered`, `error_duplicate_payer_enrollment_already_covered`). These carry no `test_recipe`; their assertions are owned by the cited difficulty instances, all of which resolve and are covered. No PRD-derivability skips were needed.

**test_helpers files created:** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Validation performed:** all modules byte-compile; test_helpers imports against the real framework; every test docstring carries exactly one `Design:` tag (75/75, no dual/untagged); all PRD citations verified verbatim in `workspace/PRD.md`; date/threshold literals recomputed from PRD prose; no `skip`/`xfail` markers and no scaffold references in emitted code.

## Step 6: Generate implementation — 2026-06-05T18:02:31.000Z

**Files created** (18 total, all under `workspace/implementation/`):
- `start.sh` — launcher; `requirements.txt` — Flask 3.0.3
- `app.py` — entry point, blueprint registration, error handlers
- `db.py` — in-memory `Store` (11 dicts keyed by id + insertion sequence), `new_id`/`now_iso`
- `errors.py` — `APIError` + full error catalog (36 error IDs → HTTP codes)
- `response.py` — success/error envelope helpers (`meta`/`response_type`/`data`; `api_request_id` `req_*`; ISO-8601 ms timestamps)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth + RBAC (6 roles)
- `routes/` — `orgs.py`, `providers.py`, `verification.py`, `sanctions.py`, `peerreview.py`, `enrollments.py`
- `services/` — `common.py`, `model.py`, `calc.py` (all 7 calculations), `posture.py` (recompute + cascade), `lookups.py`

**Stack:** Python 3 + Flask, in-memory only (module-level `store` dicts). No seeding, no disk persistence — fresh boot wipes all state.

**start.sh:** `set -euo pipefail`, `cd` to script dir, installs deps only when `import flask` fails (guarded for concurrent per-test reboots), then `exec python3 app.py`. `app.py` binds `0.0.0.0:$PORT` (default 10000), `threaded=True`, foreground.

**Coverage:** 11 entities, 51 endpoints. Implemented posture-driven `credentialing_status` (first-match-wins), readiness score (2dp ROUND_HALF_UP, pinned order), expirable banding (inclusive boundary), peer-review weighted tally with chair tie-break, OCC on file finalize (412 before state checks), cyclic re-credentialing loop (rolling vs fixed-anniversary variants), retroactive/prospective enrollment effective dates, panel capacity, and the depth-3 cascade (clock → license LAPSED → provider demotion → auto-TERMINATED enrollments with `CREDENTIALING_LAPSED`).

**Notable design decisions:** validation ordering per PRD §2.6 (FK existence priority 4 before field validation priority 5); OCC before state on finalize per §2.10; cross-org body FKs rejected as `ERR_REFERENCED_RESOURCE_NOT_FOUND`; derived-field recompute bumps version/updated_at; internal `_seq` and `original_completed_date` stripped from serialized output.

## Step 7: Run tests and iterate — 2026-06-05T18:11:16.000Z

All 8 parallel rounds pass 75/75 cleanly. (Orchestrator independently re-ran the 8-round sweep after the subagent exited to regenerate the `results.{1..8}.json` artifacts and confirm the pass — all 8 rounds 75/75.)

**Iterations run:** 2 sweeps (baseline + verification). Baseline was a stable 72/75 — the same 3 tests failed in all 8 rounds (deterministic role-ordering bug, not flaky).

**Root cause:** Three cast-vote tests issued the vote with `X-User-Role: CredentialingSpecialist`. The PRD authorizes the cast-vote endpoint only for `MedicalDirector` and `PeerReviewer` (§3.5 + endpoint table), and §2.6 evaluates role authorization (step 2) *before* the referential/segregation business checks (step 8). So a faithful PRD implementation correctly returns `ERR_INSUFFICIENT_PERMISSIONS` for a specialist casting a vote — the segregation/org-mismatch checks are never reached. The tests' request *identity* was inconsistent with the PRD (STEP 2 test bug), not a real implementation defect. The implementation's cast-vote ordering already matched the PRD.

The fix keeps the same opaque operator id `spec-1` (the provider's `initiated_by_user_id`) but has it cast in a *voting* capacity, which PRD §2.1 explicitly contemplates. This makes each test reach the exact PRD-required check.

**Tests deleted:** None. All three failing tests cover verbatim, uniquely-derivable PRD rules (§3.5 `ERR_SEGREGATION_OF_DUTIES` and `ERR_REVIEWER_ORG_MISMATCH`); only their request identity was wrong.

**Fixes applied to test_suite/ (assertion-layer request identity — STEP 2 consistency fix, made tests MORE PRD-faithful):**
- `test_suite/test_04_peer_review.py` — added `SPEC_AS_REVIEWER = make_peer_reviewer_headers("spec-1")`; switched the cast-vote calls in `test_segregation_of_duties_blocks_initiating_specialist_vote` and `test_cast_vote_referential_beats_segregation_of_duties` from `SPEC` to `SPEC_AS_REVIEWER`.
- `test_suite/test_07_difficulty_reinforcement.py` — same `SPEC_AS_REVIEWER` header added; switched the cast-vote call in `test_cast_vote_referential_error_http_409` from `SPEC` to `SPEC_AS_REVIEWER`.

**Fixes applied to test_helpers/:** None needed (helpers already exposed `make_peer_reviewer_headers(user_id)`).

**Fixes applied to implementation/:** None. The implementation was already PRD-correct.

Note: `SCAFFOLD_CORNER_DESIGN.yaml` prescribed casting as `CredentialingSpecialist` and asserting `ERR_SEGREGATION_OF_DUTIES`, which contradicts the PRD it generated (role auth precedes business checks). Per the PRD-First contract, the PRD governs, so the test request identity was corrected to a voting role.

## Step 8: Finalize PRD — 2026-06-05T18:13:09.000Z

PRD_FINALIZED.md created as a verbatim copy of PRD.md. No edits were warranted (orchestrator confirmed `diff PRD.md PRD_FINALIZED.md` is empty — byte-for-byte identical).

**PRD.md vs PRD_FINALIZED.md:** 322 lines vs 322 lines — 0% delta.

**Changes:** None. The single Step 7 item was a pure test-fixture / request-identity bug. The PRD already uniquely determines the behavior the implementation exhibits; there is no PRD silence and no PRD/impl mismatch to pin.

**Per-edit pre-edit search log (one analysis, no edits):**
- **Subject:** cast-vote role authorization, and its precedence relative to org-mismatch (`ERR_REVIEWER_ORG_MISMATCH`) and segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`) checks.
- **Impl paths enumerated:** `routes/peerreview.py` `cast_vote` (role gate `require_role(role, {"MedicalDirector","PeerReviewer"})` first, then org-mismatch → segregation → duplicate); `middleware.py` `require_auth`/`require_role` (role raises `ERR_INSUFFICIENT_PERMISSIONS` 403 before business logic); grepped all `require_role` callsites across routes/ — role auth uniformly first after auth on every endpoint, consistent with §2.6 step 2 before business checks.
- **Cross-check vs PRD:** §3.5 ("A ballot may be cast by a `MedicalDirector` or a `PeerReviewer`") + endpoint table (cast-vote: `MedicalDirector, PeerReviewer`) uniquely fix the authorized role set; §2.6 uniquely fixes role-auth ahead of business checks. A `CredentialingSpecialist` casting a vote correctly yields `ERR_INSUFFICIENT_PERMISSIONS` — exactly the implementation's behavior.
- **Wording adjustment:** None. PRD already determines the behavior uniquely and matches the implementation.

## Step 9: Complete PRD — 2026-06-05T18:19:36.000Z

All 9 edits applied cleanly as in-paragraph inserts/revisions. No new sections, no new paragraphs.

**Source vs. completed:**
- `PRD_FINALIZED.md`: 322 lines, 46,424 chars
- `PRD_COMPLETED.md`: 322 lines, 48,649 chars (char delta +2,225; no line-count change — all in-paragraph edits)

**Counts:** 9 changes — **6 ambiguity-pins**, **3 mismatch-revisions**.

**Per-change list:**
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` silently clamped (limit→[1,100], negative offset→0); non-integer values yield `ERR_INVALID_REQUEST` — services/common.py:11-42
- §2.7 Deterministic Clock — insert — ambiguity — clock endpoint takes no `org_id`, applies `current_utc` to every org store-wide, returns the last-updated org, `ERR_NOT_FOUND` when no org exists — routes/orgs.py:67-89
- §3.1 Sanctions sources — insert — ambiguity — duplicate `source_code` within an org rejected with `ERR_INVALID_REQUEST` — routes/orgs.py:206-208
- §3.2 Provider intake — insert — ambiguity — duplicate `npi` within an org rejected with `ERR_INVALID_REQUEST` — routes/providers.py:58-60
- §3.3 Re-verification — insert — ambiguity — re-opened verification request takes no body; seeded `method`=`PRIMARY_SOURCE`, empty `source_reference`, null `verified_at` — routes/verification.py:45-52
- §3.5 Cast ballot — insert — ambiguity — file-state `UNDER_REVIEW` check runs after body validation and before the three guards, which fire org-mismatch → segregation → duplicate-vote — routes/peerreview.py:176-190
- §3.5 Finalize — insert — ambiguity — omitting `decision_reason` leaves it at existing null value (not overwritten) — routes/peerreview.py:268,293-294
- §3.7 Re-cred due date — insert — ambiguity — anniversary anchor persisted/exposed as `original_completed_date` (null until first cleared) — routes/peerreview.py:319-320, routes/providers.py:74
- §3.7 Posture trigger list — revise — mismatch — posture recompute happens on start-recredentialing and NOT via first-match-wins on file finalization, which sets `credentialing_status` directly (CLEARED/CONDITIONAL) — routes/providers.py:188, routes/peerreview.py:310-336
- §3.7 Readiness trigger list — revise — mismatch — readiness also recomputed on screening recording (HIT or CLEAR) and on starting re-credentialing, created as integer `0` at intake, NOT recomputed by file finalization — routes/providers.py:293,188,71, routes/peerreview.py:298-307

Tests used only as auxiliary cross-reference, never as authority.

---

## Pipeline complete

All 9 steps finished. Final state: **75/75 tests pass across all 8 parallel stability rounds.** Task artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/ (7 files, 75 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.{1..8}.json}.
