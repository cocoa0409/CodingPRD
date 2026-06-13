# Worklog — task_0300_online_legal_document_self_service

## Step 1: Create task directory — 2026-06-11T00:00:00.000Z

Created `tasks/task_0300_online_legal_document_self_service/` and `workspace/` subdirectory (pre-assigned index 0300, no scan performed).

## Step 2: Generate scaffold (Expert) — 2026-06-11T00:00:00.000Z

All three required artifacts are in place and pass the lint clean. The directory already had a `worklog.md` and `workspace/` (orchestrator-owned). My task is complete.

Generated the three scaffold artifacts for **task_0300_online_legal_document_self_service** (LegalZoom-style online legal document self-service), targeting the **Expert** difficulty band. All three files pass `scaffold_lint.py` clean (457 calls scanned, 0 violations), and I independently verified grounds-resolution, error-code closure, enum-value closure, name uniqueness, excluded_because reference resolution, forbidden-vocabulary absence, and pre-computed all formula literals in Python.

**Files written** (all absolute):
- SCAFFOLD.yaml (1239 lines)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1336 lines)
- SCAFFOLD_CORNER_DESIGN.yaml (1411 lines)

**Scaffold profile:**
- **Archetype:** workflow_orchestration + compliance_audit; topology `flat` (api_prefix `/legal`); shape `cyclic`; role_model `peer_roles`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions.
- **Entities (14):** Customer, SubscriptionPlan, Subscription, ClauseTemplate, DocumentProject, QuestionnaireResponse, AssembledClause, DocumentRevision, Attorney, AttorneyReview, SignatureRequest, NotaryReferral, Order, UpdateReminder.
- **State machines (5):** Subscription (PAST_DUE→ACTIVE revert cycle), DocumentProject (cyclic CHANGES_REQUESTED→IN_PROGRESS revision loop; STORAGE_LOCKED cascade target), AttorneyReview (branching IN_REVIEW→{APPROVED, CHANGES_REQUESTED}), SignatureRequest (compound bubble-up to COMPLETED), UpdateReminder. Plus 1 concurrency rule (OCC `revision-create-stale-project` on DocumentProject.version, 412).
- **Calculations (6):** provisional_pricing, review_pricing, final_pricing (dual-variant provisional-vs-final, per-line round-then-sum pinned), project_completeness (dual-variant provisional-vs-assembled), credit_conservation, money_conservation.
- **Validations:** 21 priority-ordered rules across auth/existence/state/referential/constraint/safety/temporal/fiscal.
- **Endpoints (43):** flat REST under `/legal`, including filtered-list and sub-resource reverse-reachability GETs for all 13 FKs, plus 2 test-driving endpoints (`/_clock/set`, `/_reminders/dispatch_due`).
- **Errors (23):** all triggerable; domain-specific (e.g. ERR_ATTORNEY_WINDOW_CONFLICT, ERR_LEASE_TERM_OVERLAP, ERR_REVISION_SUPERSEDED, ERR_STALE_PROJECT_VERSION, ERR_NO_CREDITS_REMAINING).
- **Roles (3):** Customer (entity_backed), Attorney (entity_backed), PlatformAdmin (opaque).

**Difficulty design:** all 9 §0.5 rules with exactly 2 instances each (18 total), each with executable setup→trigger→assert chains and pre-computed literals. **Corner design:** 34 instances (30 active breadth probes + 4 `excluded_because` stubs deferring to §1.8).

## Step 3: Copy INSTRUCTION.md — 2026-06-11T00:00:00.000Z

Copied `INSTRUCTION.md` (53 lines) into `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-11T00:00:00.000Z

**PRD generated:** `workspace/PRD.md` — 266 lines, 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue), 18 subsections.

- **§4 endpoint table:** 43 rows (Method, Path, Description, Authorized Role(s)) — matches all 43 scaffold endpoints.
- **§5 error table:** 23 rows — matches all 23 scaffold errors.
- All three Hard Contracts PASS (Field-Name Coverage: 60 fields + extras + 37 enum/state values + 23 error IDs; Rule Coverage: validations ordering, OCC, 5 state machines incl. 4-hop cascade, 6 calculations, sibling-branch symmetry; §3 Path Purity: 0 path tokens in 347 scanned).
- Coverage notes: §2.2 byte-verbatim sentinels intact; AssembledClause is the only `common_fields:false` entity; attorney window half-open `[start,end)`, lease term closed + 7-day buffer; withheld difficulty/corner files not opened.

## Step 5: Generate unit tests — 2026-06-11T00:00:00.000Z

Generated complete test infrastructure for task_0300 (EXPERT band) under the design-index-only contract.

**Tests emitted — 67 total, all PRD-cited and Design-tagged:**
- **Queue A (Difficulty): 36 tests** covering all 18 instances across 9 rules at ≥2 tests each. Rules: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
- **Queue B (Corner): 31 tests** covering all 30 non-stub instances at ≥1 test each. Sections: entities (8), state_machines (5), calculations (2), validations (8), rbac (4), cross_cutting_complexity_layers (2), consistency_model (1).
- **Instances skipped: none failed the PRD filter.** The 4 `excluded_because:` Corner stubs correctly NOT translated. One second-coverage test steered from reminder-cancel hop (PRD-unreachable) to refund hop.

**test_helpers/ (9 files):** __init__.py, types.py, api_client.py (all 40 endpoints), api_errors.py (23 errors), assertions.py (AssembledClause asserts NO version/updated_at), factories.py, constants.py, test_users.py (make_customer_headers/make_attorney_headers), fixtures.py.
**test_suite/ (7 files):** conftest.py + test_01_pricing_and_completeness, test_02_state_machines, test_03_cascades_and_invariants, test_04_validations_and_boundaries, test_05_entities_rbac_occ, test_06_difficulty_second_coverage.
**Verification:** all compile; imports resolve; 67 tests = 67 Design lines; no skip/xfail; no scaffold leakage.

## Step 6: Generate implementation — 2026-06-11T00:00:00.000Z

**Stack:** Python 3 + Flask 3.0.3, in-memory storage only (dicts keyed by id), store empty on every boot, no seeding. `start.sh` reads `$PORT`, binds `0.0.0.0`, exec's foreground. Boots ~1s, store empty at boot.

**Modules (24 files):** app.py, db.py, response.py, middleware.py, errors.py, validators.py, common.py (round-half-up money), constants.py; routes/ (15 files: customers, plans, subscriptions, clause_templates, document_projects, assembled_clauses, document_revisions, attorneys, attorney_reviews, signature_requests, notary_referrals, orders, update_reminders, system); services/ (pricing.py, cascades.py).

**Endpoints:** all 43 (14 entity collections + 2 test-driving system endpoints).
**State machines (5):** Subscription, DocumentProject (10-state cyclic), AttorneyReview (branching), SignatureRequest (compound bubble-up), UpdateReminder.
**Cascades:** Subscription→CANCELLED depth-4 chain (lock projects→cancel reviews→refund surcharges→cancel reminders), every hop bumps updated_at/version.
**Calculations:** provisional/final pricing (per-line discount + round-half-up before sum; WILL+CA 5838 example), review surcharge (7500), final invoice additive, provisional-vs-assembled completeness (live denominator at finalize), credit + money conservation.
**Key decisions:** validation order per PRD §2.9 (401→403→404→409ref→400→412OCC→409state→business); attorney-review uses PRD §3.5 prose order (PRD wins over scaffold table); FK presence/type (400) before existence (404); lease 7-day buffer (gap of exactly 7 allowed); attorney windows half-open; AssembledClause id/created_at only; logical clock drives reminders + signing instant (due_at = sign + 90 days).

## Step 7: Test-iterate loop — 2026-06-11T00:00:00.000Z

All 8 parallel rounds clean: 66/66 passed, 0 failed, 0 errors in every round.

**Iterations run:** 2 (initial sweep + 1 fix sweep).

**Initial state:** 1 test failed identically across all 8 rounds (`test_review_approved_releases_window_and_assembles_project`), failing with `Expected 201, got 409 ERR_ATTORNEY_WINDOW_CONFLICT`.

**Tests deleted (1):**
- `test_review_approved_releases_window_and_assembles_project` (in `test_suite/test_06_difficulty_second_coverage.py`) — **STEP 1b unique-derivability collapse, BRANCH-ASYMMETRIC SIDE EFFECT category.** Scaffold rule: `Difficulty/non_linear_state_machine/attorney_review_branch_approved_vs_changes_requested`. The test asserted that after a review reaches APPROVED, the attorney's window is "released" so a new review reusing the same attorney+window succeeds (201). But PRD §3.5's only explicit window-conflict predicate is "it must not overlap any other non-CANCELLED review already held by the same attorney." An APPROVED review is non-CANCELLED, so under the literal predicate it still occupies the window → 409. "The attorney's window is released" (§3.5) does not uniquely determine APPROVED reviews are removed from the overlap set; the only place PRD ties "window released" to a conflict-set change is the storage-lock cascade (§3.8) where the review simultaneously becomes CANCELLED (explained by §3.5's CANCELLED exclusion). §3.7 keeps APPROVED reviews live and summed into final_invoice_cents. Two divergent PRD-faithful implementations articulable → deletion mandated.

**Fixes applied to test_helpers/:** None.
**Fixes applied to implementation/:** None. `_window_conflicts` (`routes/attorney_reviews.py`) already faithfully encodes the PRD's explicit non-CANCELLED overlap predicate; weakening it would violate the cardinal rule.

**Final state:** 8/8 parallel rounds clean — 66 passed / 66 total / 0 failed / 0 errors in every round.

## Step 8: Finalize PRD — 2026-06-11T00:00:00.000Z

**Line counts:** PRD.md = 266 lines; PRD_FINALIZED.md = 266 lines. %-delta = 0% (both edits inline; no lines added/removed). Two lines (§3.5, lines 154 and 158) modified.

**Changes:**
- §3.5 (line 154) — **revise** — Pinned that the window-overlap predicate excludes *only* CANCELLED reviews; REQUESTED/ASSIGNED/IN_REVIEW/APPROVED/CHANGES_REQUESTED reviews all still occupy their window, so a terminal APPROVED/CHANGES_REQUESTED does not free the window for reuse — `routes/attorney_reviews.py:18-33` (`_window_conflicts`).
- §3.5 (line 158) — **revise** — Replaced the two branch-site "the attorney's window is released" phrases (APPROVED and CHANGES_REQUESTED branches) with wording that no longer implies window-reuse freeing; added a parenthetical noting the APPROVED review remains a live, non-CANCELLED record that still occupies its scheduling window — `routes/attorney_reviews.py:153-181`.

**Root cause:** Step 7 deleted `test_review_approved_releases_window_and_assembles_project`, which asserted an APPROVED review's window is reusable (201) by a new overlapping review. Impl's `_window_conflicts` only excludes CANCELLED, so an APPROVED review still blocks → 409. Edits pin the literal predicate as authority and de-ambiguate "window released". Cascade path (§3.8/line 186, where review becomes CANCELLED — the genuine release) left untouched.

## Step 9: Complete PRD — 2026-06-11T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`.

**Source vs. completed:** PRD_FINALIZED.md 266 lines / 42,973 bytes → PRD_COMPLETED.md 266 lines / 44,956 bytes (char-delta **+1,983**). All in-paragraph inserts/revisions; no new sections, line count unchanged.

**Counts:** 6 ambiguity-pins, 1 mismatch-revision.

**Changes:**
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset are *clamped* (limit→[1,100], offset→≥0) not rejected; non-integer → ERR_INVALID_REQUEST. — `middleware.py:78-97`
- §3.3 Questionnaire — insert — ambiguity — GET questionnaire returns a paginated array envelope (zero or one response), not a bare object. — `routes/document_projects.py:234-244`
- §3.3 Questionnaire — insert — ambiguity — defines "non-empty value" (not null/empty-or-whitespace-string/empty-list/empty-object); count over all non-empty answers entries (pre-cap), regardless of key. — `services/pricing.py:38-55`
- §3.6 Revisions — insert — ambiguity — supplied expected_document_project_version persisted verbatim on the created revision. — `routes/document_revisions.py:55`
- §3.7 Finalization/Storage — insert — ambiguity — customer project-transition endpoint accepts only IN_PROGRESS/FINALIZED/STORED/ABANDONED; server-only targets (SIGNED, STORAGE_LOCKED, …) refused with ERR_INVALID_STATE. — `routes/document_projects.py:309,365-367`
- §3.7 Reminders — insert — ambiguity — reminder due_at base ("moment of signing") = logical clock when set, else server wall-clock. — `routes/signature_requests.py:155-174`
- §3.7 Reminders — **revise** — **mismatch** — PRD claimed a not-yet-due reminder dispatched "directly" is refused with ERR_REMINDER_NOT_DUE; impl has no per-reminder dispatch endpoint and the bulk sweep leaves future reminders SCHEDULED (no-op) and never returns ERR_REMINDER_NOT_DUE. — `routes/system.py:25-47` (error declared but never raised, `errors.py:37`)
- §3.8 Lease — insert — ambiguity — lease-term overlap check runs only when creation supplies all three of lease_property_ref/lease_start_date/lease_end_date; otherwise skipped. — `routes/document_projects.py:114-120`

**Notes:** PRD already tightly pinned on pricing formulas, completeness ratios, state machines, cascades, validation ordering, money/credit conservation — no changes needed there.

---

## Pipeline complete — 2026-06-11T00:00:00.000Z

All 9 steps complete. Final state: **66/66 tests passing across all 8 parallel stability rounds.** Artifacts present: SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/ (9 files), test_suite/ (7 files), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}. Difficulty: Expert.
