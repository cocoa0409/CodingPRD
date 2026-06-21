# Worklog — task_0254_passport_application_processing

## Step 1: Create Task Directory — 2026-06-08T00:00:00.000Z

Created `tasks/task_0254_passport_application_processing/` with `workspace/` subdirectory. Output folder pre-allocated; no ID rescan performed.

## Step 2: Generate Scaffold (Expert difficulty band) — 2026-06-08T00:00:00.000Z

Run in two parts because the first scaffold-generator subagent (agentId a16a203da021989fc) hit a stream idle timeout after writing SCAFFOLD.yaml (1478 lines) and SCAFFOLD_DIFFICULTY_DESIGN.yaml (1367 lines) but before writing the corner-design file. It returned no summary (timeout). A fresh focused subagent then generated the missing SCAFFOLD_CORNER_DESIGN.yaml, reading the existing SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml for consistency. Corner-design subagent summary (verbatim):

**Structure:** Single top-level key `scaffold_corner_design`, following the §1.9 schema exactly (per-section instances, each with `name`, `claim_type`, `grounds`, `distinguishing_aspect`, and a structured `test_recipe` of `setup` / `setup_api_calls` / `trigger` / `assert`; `excluded_because:` stubs carry no `test_recipe`).

**Counts:** 8 corner sections, 54 total instances (46 active + 8 `excluded_because:` stubs that defer to named §1.8 depth instances to avoid duplicating queue A).

**Coverage by section** (taxonomy taken verbatim from `references/claim-extraction-guide.md`):
- **entities (16):** creation/retrieval/listing/pagination, not-found (404) vs FK-not-found (422), required-field & default (service_level ROUTINE), computed `is_minor` boundary (strictly <16, incl. exactly-16 false), system-field minting, enum/range/non-positive type constraints, Photo immutability (`common_fields:false`, no version), unique-email rejection, FK integrity on the polymorphic appointment counter.
- **state_machines (11):** initial state, valid DRAFT→SUBMITTED side-effects, invalid-from rejections (begin-verification from DRAFT, clear-hold from IN_VERIFICATION, complete from CANCELLED), terminal lockdown (withdraw from ISSUED), pay-twice idempotency, issue→appointment-COMPLETED cascade, name-change APPROVE applying full_legal_name; cyclic/parallel shapes stubbed to §1.8.
- **calculations (9):** adult BOOK_AND_CARD bundle (18500), RENEWAL no-execution (13000), CARD default delivery branch (6500), multi-reason & ratio photo_validation, revalidate FAIL→PASS, summary doc-progress counts; SLA & risk-score variants stubbed to §1.8.
- **validations (8):** payment-amount-mismatch, no-PASS-photo, MINOR guardian-consent, name-change-evidence, invalid-interval, duplicate-urgent-appointment; fee-unpaid gate & state/fiscal priority stubbed to §1.8.
- **errors (2):** explicit ERR_STALE_VERSION 412 on submit (`${app_v0} - 1`); the appointment-OCC error stubbed.
- **rbac (5):** unauthenticated (401, headerless), two role-denial 403s (Applicant→adjudicate, AcceptanceAgent→facility), the verify-leg SoD (different agent than `assigned_acceptance_agent_id`); adjudicator-equals-agent SoD stubbed to §1.8.
- **cross_cutting_complexity_layers (2):** OCC version-increments-on-write, derived-field `total_fees_paid_cents` reconciliation after pay.
- **consistency_model (1):** immediate visibility of urgent-surcharge re-derivation after booking.

**Consistency:** Every instance references only real SCAFFOLD.yaml entities/fields/endpoints/error_ids/roles. All JSONPaths are quoted, all OCC inputs use `${var}` references, all `${var}` placeholders are bound by prior `captures:`, and all 8 stub references resolve to actual §1.8 instance names.

**Note on YAML lint:** the corner subagent reported `scaffold_lint.py` aborts before reaching the corner file because the pre-existing SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml do not parse under PyYAML (SCAFFOLD.yaml: `constraints: > 0` / `>= 0` block-scalar bugs and `input: [..., field?]` flow-sequence `?` suffixes; difficulty file: unquoted JSONPaths like `{ fee_id: $.data[0].id }`). A follow-up syntax-only normalization pass (Step 2c below) is being run to make all three parse and lint clean before continuing.

## Step 2c: Scaffold YAML syntax normalization — 2026-06-08T00:00:00.000Z

Syntax-only normalization subagent summary (verbatim): edits were quoting-only, zero semantic changes.
- **SCAFFOLD.yaml** — 20 edits: 3 block-scalar comparison constraints quoted (`"> 0"`, `">= 0"`); 17 lines / 43 optional-marker `?` tokens in flow-sequence `input:` lists quoted (e.g. `"guardian_applicant_id?"`, `"limit?"`, `"offset?"`).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 133 `captures:` lines / 160 JSONPath values quoted (every `$.data...` inside `captures: { ... }`).
- **SCAFFOLD_CORNER_DESIGN.yaml** — 0 edits (already parsed).

Final state: all three parse under `yaml.safe_load`. `scaffold_lint.py` exit 1 with **15 violations, all rule (f) FK_REVERSE_UNREACHABLE** in SCAFFOLD.yaml (FK fields lacking a reverse-navigation endpoint). All other lint rules pass — notably NO §1.8/§1.9-vs-§1.5 unknown-endpoint violations, so the test designs are consistent with the endpoints §1.5 actually declares.

**Orchestrator decision: ACCEPT the 15 FK_REVERSE_UNREACHABLE findings as non-blocking.** Rationale: (1) Step 2 only requires the three files to exist and be LLM-readable; downstream steps do not strict-parse. (2) Designs are consistent with declared §1.5 endpoints. (3) Per-test-server isolation makes reverse-listing return single-item lists where needed, so side-effect-created entities (e.g. FeeAssessment) are still resolvable via `$.data[0]`. (4) Resolving them requires adding endpoints/query-params — a semantic design expansion that would add PRD+impl surface not covered by any test and risk new inconsistencies; Steps 7–9 already reconcile genuine endpoint gaps. FKs flagged: Applicant.guardian_applicant_id, Application.{applicant_id, assigned_acceptance_agent_id, adjudicator_id}, AcceptanceAgent.facility_id, SupportingDocument.{application_id, reviewed_by_agent_id}, Photo.application_id, FeeAssessment.application_id, Appointment.{application_id, facility_id, counter_id}, AdjudicationDecision.{application_id, adjudicator_id}, ApplicationStatusEvent.application_id.

## Step 3: Copy Shared Files — 2026-06-08T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-08T00:00:00.000Z

doc-generator subagent summary (verbatim):

Generated `workspace/PRD.md` (~303 lines) from SCAFFOLD.yaml (passport-application-processing). DIFFICULTY/CORNER design files withheld.

**Document metrics:** 5 top-level sections (Introduction; Global Specifications; Business Logic & Workflows; Endpoint Definitions; Error Code Catalogue). §2: 9 subsections (RBAC, Response Structure, Pagination, Common Properties & Versioning, Monetary Precision, Status History/Audit, OCC, Nested Retrieval & Existence Ordering, Validation Ordering & Error Precedence). §3: 9 lifecycle subsections.

**Scaffold coverage:**
- Entities (11): all 60 field names present; Photo and ApplicationStatusEvent noted as id/created_at only (no updated_at/version).
- State machines (5): Application main lifecycle (DRAFT→SUBMITTED→IN_VERIFICATION→ADJUDICATING/REVIEW_HOLD→APPROVED→ISSUED, plus REJECTED/WITHDRAWN + review/return cyclic loop), parallel name_change_status dimension, SupportingDocument, FeeAssessment, Appointment — transitions with from/to, preconditions→error IDs, side effects (cascades, refunds, appointment cancellation, version increments).
- Calculations (5): fee_assessment (bundle+minor worked values 15000/10500), verification_risk_score (0.40/0.35/0.25 weights, provisional 75.00 vs final, round-half-up 2dp), processing_sla_target (forward-looking vs chronological, 42/21 calendar days), photo_validation (600px, 0.98–1.02 ratio, 0.50–0.69 head fraction, 0.69-pass/0.70-fail boundary, four failure codes), fee_ledger_conservation.
- Validations (18): full priority ordering as ordered list in §2.9; each matchable to its error ID; applies_to scopes enumerated.
- Endpoints (43): 4-column summary table; all request-body/query/path identifiers (incl. to_iso8601, expected_application_version) reach reader via §3 narrative.
- Errors (19): 2-column catalogue; every error ID also referenced in §2/§3 narrative with trigger.
- RBAC (3 roles): Applicant, AcceptanceAgent, Adjudicator; SoD tie (assigned_acceptance_agent_id vs adjudicator) covered.
- OCC: both concurrency_rules (appointment booking + submit) expressed via expected_application_version / ERR_STALE_VERSION / 412.

**Hard contracts:** Contract 1 (Field-Name Coverage) PASS — 66 identifiers, 0 missing. Contract 2 (Rule Coverage) PASS. Contract 3 (§3 Path Purity) PASS — 408 §3 backtick tokens, 0 path/method leaks. §2.2 verified byte-for-byte.

## Step 5: Generate Unit Tests — 2026-06-08T18:03:45.000Z

unit-test-generator subagent summary (verbatim):

The complete test infrastructure is generated and verified. Here is my final report.

Generated complete test infrastructure for `task_0254_passport_application_processing` from the two design indices (the only test source), under strict PRD-first adjudication.

### Stage 1 — `test_helpers/` (9 files, 1120 lines)
- **types.py** — status enums + entity TypedDicts. `Photo` and `ApplicationStatusEvent` are `common_fields: false`, so their TypedDicts omit `updated_at`/`version`.
- **api_client.py** — one method per endpoint (48 methods) subclassing `GenericApiClient`.
- **api_errors.py** — all 19 error IDs + HTTP-status map, registered with the framework.
- **assertions.py** — per-entity assertions; append-only checker forbids `version`/`updated_at`; fee-total-consistency invariant.
- **factories.py**, **constants.py**, **test_users.py** (all three roles `entity_backed`, so per-instance `make_*_headers` builders are provided), **fixtures.py** (lifecycle tiers: draft→submitted→paid→in-verification→adjudicating→approved/issued, plus name-change and appointment composites; identity threaded via real entity ids), **__init__.py** barrel.

### Stage 2 — `test_suite/` (7 files + conftest, 81 tests)
- **Queue A (Difficulty):** all 18 instances × exactly 2 tests = 36 tests.
- **Queue B (Corner):** 45 of 46 non-stub instances × 1 test. All 8 `excluded_because:` stubs correctly NOT translated (cross-references verified to resolve).

### Key PRD-first adjudication decisions
1. **Skipped `Corner/entities/unique_email_duplicate_applicant_rejected`** — the only non-stub instance not emitted. PRD §3.1 states email must be unique, but PRD prose never names the error_id for a duplicate (ERR_VALIDATION is only tied in prose to field-range violations). The asserted `ERR_VALIDATION` is not uniquely-derivable, so the instance was skipped per the Core rule (gap left as a gap, no xfail/placeholder).
2. **`Difficulty/.../application_name_change_parallel_dimension_independent_of_main_status`** — the source instance's third assertion (main status == ADJUDICATING after the name-change-evidence accept) contradicts PRD §3.6, which holds the application in `IN_VERIFICATION` while `name_change_status` is `EVIDENCE_VERIFIED` (auto-advance requires NONE/APPROVED). My two tests assert the PRD-derivable name_change transitions (NONE→PENDING_EVIDENCE at creation; →EVIDENCE_VERIFIED on accept) plus the correct held main status, which is exactly the "independent axes" the instance probes. The non-PRD-derivable ADJUDICATING claim was dropped.

### Verification performed
- `test_helpers` imports cleanly against the framework; all 81 tests collect with no import/syntax errors; `py_compile` passes.
- Coverage audit: 18/18 difficulty instances (2 each), 45/46 corner non-stubs (1 each), 8/8 stubs untranslated with resolving cross-references.
- Every test docstring carries exactly one `Design:` tag (0 untagged/dual-tagged); distinctive citation substrings verified to survive a literal grep of PRD.md; zero "scaffold"/"Table N"/"§1.x" leakage in generated code.

Note: tests were not executed live (no implementation exists yet under `workspace/`); validation was limited to import/collection/compile plus static citation and coverage audits.

## Step 6: Generate Implementation — 2026-06-08T18:03:45.000Z

implementation-generator subagent summary (verbatim):

The implementation is complete. All modules compile and the full directory structure is in place.

I generated a complete Python + Flask implementation for the Passport Application Processing API at `workspace/implementation/`.

### Structure
- `start.sh` — guarded-install launcher (`exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000); skips `pip install` when Flask is already importable to avoid per-test-reboot contention
- `app.py` — Flask entry point, blueprint registration, global error handlers; empty in-memory stores on every boot (no seeding)
- `db.py`, `response.py`, `errors.py`, `middleware.py`, `routes/_helpers.py` — foundation (logical clock, envelope helpers, full error catalog, auth/RBAC, pagination)
- `routes/` — applicants, applications, documents, photos, fees, appointments, infrastructure (facilities/counters/agents/adjudicators), decisions, clock
- `services/calculations.py` + `services/domain.py` — fee assessment, weighted risk score, SLA, photo validation, cascade transitions, compensation

### Verified behavior (all smoke suites pass)
- Response envelope (`meta`/`response_type`/`data`), error body (`error_id`/`message`), pagination (`limit`/`offset`/`total_count`/`has_more`) exactly per scaffold
- Auth via `X-User-ID`/`X-User-Role` (roles `Applicant`/`AcceptanceAgent`/`Adjudicator`); `/applicants` and `/_clock/set_current_utc` anonymous; full RBAC matrix
- Full lifecycle DRAFT→SUBMITTED→IN_VERIFICATION→ADJUDICATING→APPROVED→ISSUED, plus REVIEW_HOLD/REJECTED/WITHDRAWN branches and the parallel name-change sub-status
- Fee math: adult/minor age bands, BOOK_AND_CARD bundle discount, execution/expedite/urgent/delivery surcharges, integer cents; conserved fee ledger with pay/refund neutrality
- Risk score: provisional (75.00 with PASS photo, docs pending) vs final; strict `>50` REVIEW_HOLD gate (fires mid-verification)
- Auto-advance out of verification gated on all-required-accepted AND name-change ∈ {NONE, APPROVED}
- Two appointment interval semantics (half-open facility overlap; buffer-extended counter window), single-urgent constraint, urgent surcharge flip + fee re-derivation, OCC via `expected_application_version` (ERR_STALE_VERSION/412)
- Photo boundary precision (0.69 PASS / 0.70 FAIL), forward-looking vs chronological SLA (42/21 days), SoD enforcement, validation-priority error precedence

### Key design note
Three initial test "failures" were flawed test expectations, not implementation bugs — the review-hold gate correctly fires on the first document accept whenever final risk exceeds 50 (e.g., low-quality docs hit 71.0 after one accept), and an unresolved name-change correctly holds an application in IN_VERIFICATION even when all required docs are accepted. Both confirmed correct against the PRD. No language/dependency issues; Flask 3.0.3 already present, all modules compile, server boots cleanly via `start.sh` with an empty store.

## Step 7: Run Tests and Iterate — 2026-06-08T18:03:45.000Z

diagnostic subagent summary (verbatim):

Clean exit — all 8 parallel rounds pass 81/81.

**Iterations run:** 1 fix-batch iteration (baseline sweep → diagnose → fix → confirming sweep). Baseline was a stable 74/81 across all 8 rounds (7 deterministic failures, no flakiness).

**Tests deleted:** None. All 7 failing tests assert rules that are verbatim-covered by the PRD and uniquely derivable. Every failure was a test_helpers bug, not a coverage/derivability problem.

**Fixes applied to `test_helpers/`:**

- `fixtures.py` — added `unique_email` to the `.factories` import list. The CRUD tests call `fx.unique_email(...)` (where `fx` is the `fixtures` module), but the symbol lived only in `factories` and was never re-exported, raising `AttributeError`. This single wiring bug masqueraded as 4 independent failures (`test_create_applicant_returns_201_with_all_fields`, `test_applicant_is_minor_true_under_16`, `test_applicant_is_minor_false_exactly_16`, `test_system_fields_server_minted`).

- `fixtures.py` — added a new helper `accept_documents_clearing_holds(...)`. Per PRD §3.6 the FINAL risk gate fires on every document-status change, so accepting one required doc while its sibling is still PENDING (factor quality 0) pushes risk above 50 and forces REVIEW_HOLD; the next accept is then correctly rejected with `ERR_INVALID_STATE`. The helper walks the faithful PRD path: after each non-final accept, if the app sits in REVIEW_HOLD, a distinct adjudicator clears the hold (PRD §3.6 clear-hold capability) so verification can continue. Used by the two `test_04` cascade tests, whose setups previously accepted two docs back-to-back and tripped the hold (risk 60.60 after the first accept).

- `fixtures.py` — `name_change_evidence_verified` fixture now attaches the full required document set (IDENTITY + CITIZENSHIP + NAME_CHANGE_EVIDENCE, all quality 100) and accepts IDENTITY/CITIZENSHIP before the evidence doc. The old fixture attached only the NAME_CHANGE_EVIDENCE doc, leaving identity/citizenship factors at 0, so the FINAL risk was 75 (>50) and the app landed in REVIEW_HOLD — contradicting the test's `status == IN_VERIFICATION` assertion. With all factors at 100 the risk is 0 (no hold), and the application is held in IN_VERIFICATION purely by the name-change dimension (EVIDENCE_VERIFIED ≠ NONE/APPROVED blocks auto-advance), which is exactly the PRD §3.6 rule the test cites. The second consumer (`test_name_change_decide_approve_sets_status_approved`) is unaffected since it operates only on the name-change sub-status.

**Fixes applied to `test_suite/`:**

- `test_04_cascades_and_compensation.py` — `test_last_doc_accept_recomputes_risk_to_50_10` and `test_last_doc_accept_above_threshold_lands_in_review_hold` now use `accept_documents_clearing_holds` with a distinct adjudicator instead of two raw back-to-back `accept_document` calls. Assertions (final risk == 50.10; final status == REVIEW_HOLD) are unchanged and PRD-faithful.

**Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful for all 7 failures — it correctly fired the review-hold gate on intermediate document accepts and correctly rejected verification on a non-`IN_VERIFICATION` parent. Weakening either check would have violated PRD §3.6.

## Step 8: Finalize PRD — SKIPPED — 2026-06-08T18:03:45.000Z

**Decision: SKIP Step 8 (no PRD_FINALIZED.md produced).** Step 7 applied **0 implementation/ fixes**, **0 test deletions**, and **0 assertion weakenings**. The only Step 7 changes were test_helpers/ + test_suite/ fixture-construction repairs (missing `unique_email` re-export; fixtures corrected to walk the PRD §3.6 risk-gate / clear-hold path; `name_change_evidence_verified` given the full required doc set). The Step 7 subagent confirmed the implementation was already PRD-faithful for every failure and cited PRD §3.6 as already stating the governing risk-gate rule verbatim — i.e. these fixture bugs reveal no PRD-silence or PRD-vs-impl mismatch for Step 8 to patch. Per the resume directive (generate PRD_FINALIZED.md only if Step 7 had implementation fixes) and the SKILL's Step 8 purpose (patch PRD where Step 7's *implementation* revisions/deletions/weakenings expose ambiguity), there is nothing for Step 8 to align. Step 9 (mandatory full PRD-vs-implementation scan) runs next from `workspace/PRD.md` and will pin any residual silence/mismatch comprehensively.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-08T18:03:45.000Z

completeness-scan subagent summary (verbatim):

**Source vs completed file:**
- `PRD.md` (source — PRD_FINALIZED.md does not exist): 303 lines, 47,094 chars
- `PRD_COMPLETED.md`: 303 lines, 51,922 chars
- Char delta: **+4,828**; line delta: **0** (all edits are in-paragraph inline inserts/revisions; no new paragraphs or sections)

**Counts:** 13 changes total — **7 ambiguity-pins**, **6 mismatch-revisions**.

**Per-change log** (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.3 Pagination — insert — ambiguity — invalid `limit`/`offset` (non-integer, limit out of [1,100], negative offset) → `ERR_INVALID_REQUEST` 400 — `routes/_helpers.py:21-34`
- §2.3 Pagination — insert — ambiguity — list tie-break: equal `created_at` ordered by monotonic creation sequence — `routes/_helpers.py:148-149`, `db.py:75-77`
- §2.6 Audit trail — revise — mismatch — no event appended at creation (first event is DRAFT→SUBMITTED, `from_status` never null); `actor_role` is literal `"system"` for system-driven transitions — `routes/applications.py:62-124`, `services/domain.py:126-163`
- §2.9 Error precedence — insert — mismatch — `decision` field on the two decide endpoints validated up front (before terminality/state); `outcome` on verify stays priority-18 — `routes/applications.py:302-313,394-396`, `routes/documents.py:110-125`
- §3.1 Applicant registration — insert — ambiguity — duplicate email → `ERR_INVALID_REQUEST` 400; missing `guardian_applicant_id` → `ERR_FK_NOT_FOUND` 422 — `routes/applicants.py:76-86`
- §3.1 Infrastructure — insert — ambiguity — duplicate `badge_number`/`passport_office_code` → `ERR_INVALID_REQUEST` 400; missing agent `facility_id` → `ERR_FK_NOT_FOUND` 422 — `routes/infrastructure.py:92-97,136-138`
- §3.2 requires_execution — insert — ambiguity — no mail-eligibility signal exists, so every name-change-requested RENEWAL is treated as not mail-eligible (requires_execution true) — `routes/applications.py:94-97`
- §3.4 Name-change decide — revise — mismatch — `decision` enum is exactly `APPROVE`/`DENY`; no separate "new legal name" field (approve is an identity write of existing `full_legal_name`); terminal sub-state (`APPROVED`/`DENIED`) → `ERR_ALREADY_TERMINAL` while `NONE`/`PENDING_EVIDENCE` → `ERR_NAME_CHANGE_EVIDENCE_REQUIRED`; approve re-evaluates auto-advance — `routes/applications.py:389-427`
- §3.5 Fees — revise — mismatch — `one_day_delivery` is a stored field defaulting false; no endpoint accepts it as input, so the component is effectively always 0 — `routes/applications.py:228-240`, `services/calculations.py:74`
- §3.6 Risk score — revise — mismatch — risk aggregates documents/photos across **all** of the applicant's applications, not just the current one — `services/calculations.py:105-128`
- §3.6 Risk score (provisional) — insert — ambiguity — both variants use identical applicant-wide formula; only the set of accepted docs differs — `services/calculations.py:131-141`
- §3.6 Auto-advance — insert — ambiguity — required set defined by category (IDENTITY+CITIZENSHIP always; +GUARDIAN_CONSENT for MINOR; +NAME_CHANGE_EVIDENCE when requested); a category is accepted with ≥1 ACCEPTED doc — `services/domain.py:34-68`
- §3.8 Summary — insert — ambiguity — `required_docs_*` counted per required category; `total_due_cents` is 0 before a fee assessment exists — `routes/applications.py:150-166`, `services/domain.py:52-63`
- §3.9 Adjudicate / §4 endpoint table — revise — mismatch — approve fee-unpaid → `ERR_FEE_UNPAID` (after SoD); clock endpoint row corrected to anonymous (no role), matching §2.1 — `routes/applications.py:322-326`, `routes/clock.py:21-28`

(The §3.9 row covers two related edits — the approve `ERR_FEE_UNPAID` pin and the §4 clock-row anonymous correction — counted as one mismatch-revision pair; total distinct edit operations = 14 across 13 logged bullets.)

Tests were used only as auxiliary cross-reference (confirmed risk-score scope, `APPROVE`/`DENY` enum, anonymous clock, uniqueness behavior); the implementation was the sole alignment authority.

## Final verification sweep (orchestrator) — 2026-06-08T18:03:45.000Z

The Step 7 subagent reported a clean 8-round sweep but cleaned up its `results.*.json` evidence files on exit, leaving the SKILL-mandated per-round result artifacts absent. The orchestrator re-ran the canonical 8-round parallel `prd-bench-local-run --isolation per-test-server` sweep against the exact post-Step-7 implementation + test state to (a) regenerate the durable evidence and (b) independently confirm green. Result: **all 8 rounds passed 81/81 (0 failed)**. `results.{1..8}.json` now persist under `workspace/implementation/`. Pipeline complete.
