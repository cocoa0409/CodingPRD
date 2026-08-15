# Worklog — task_1456_clinical_documentation_improvement

## Step 1: Create Task Directory — 2026-08-13T09:03:00.000Z

Task directory `tasks/task_1456_clinical_documentation_improvement/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per command args (no index scan, no other task_* writes).

## Step 2: Generate Scaffold — 2026-08-13T09:44:36.000Z

All three files are properly structured. Final summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/`):

1. **`SCAFFOLD.yaml`** — §1.0–§1.7 (no `scaffold_difficulty_design` or `scaffold_corner_design` keys)
2. **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — single top-level `scaffold_difficulty_design:` (§1.8)
3. **`SCAFFOLD_CORNER_DESIGN.yaml`** — single top-level `scaffold_corner_design:` (§1.9)

**Counts:**
- Entities: **11** (CDIProgram, EscalationPolicy, Provider, PatientCase, CDIReview, CDIQuery, QueryResponse, ReconciliationEvent, DenialRiskTarget, ProviderEducationEvent, CMISnapshot)
- Endpoints: **52**
- Error codes: **21**
- Roles: **6** (CDIManager, CDISpecialist, HIMCoder, Provider [entity-backed], ComplianceAuditor, SystemAdmin)
- State machines: **5** (CDIProgram, PatientCase, CDIReview with cycle ACTIVE↔ON_HOLD, CDIQuery with self-loop ESCALATED→ESCALATED, ReconciliationEvent)
- Calculations: **6** (including dual-variant priority score, nested-rounding CMI snapshot, threshold-banded education score, pattern-matching non-leading lint)
- Validations: **18** ordered by priority
- Concurrency rules: **3** OCC rules (review close, case finalize, query send)
- §1.8 instances: **18** (2 per rule × 9 rules — all rule_ids covered)
- §1.9 instances: **42** (31 with full test_recipe + 11 `excluded_because` stubs citing §1.8 coverage)

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (375 calls scanned, 0 violations)

**Notable design decisions (harder-than-expert calibration):**
- **Flat topology** (`api_prefix: /api`) — chosen over hierarchical for diversity (skill notes 0% of existing examples use flat).
- **Cyclic + self-loop state machines** — `CDIReview: ACTIVE↔ON_HOLD` cycle; `CDIQuery: ESCALATED→ESCALATED` self-loop driven by clock advance; both fork to terminal states (RESPONDED/NO_RESPONSE/CANCELLED) with distinct side-effect sets.
- **Compound invariant across compensating actions** — AGREE response mutates working DRG; later `CODER_PREVAILS` reconciliation restores it, while `CDIReview.opportunity_*_delta` deliberately does NOT roll back (audit-trail preservation).
- **Multi-branch non-linear priority score** — `priority_score = base_opp × acuity_mult × los_factor × 100` where `acuity_mult` is a 4-branch piecewise on `(working_soi, working_rom)` and `los_factor` is a 3-branch on `(current_period, discharge_period)`; dual variant (provisional vs residual) keyed on whether any query is open.
- **Nested-rounding CMI** — round each ratio to 4 dp before subtraction (pinned rounding order).
- **Threshold boundaries** — education flag at 85/70/50 with `>=` semantics; LOS factor at `==` vs `>` discharge_period.
- **OCC on three entities** — version conflicts on review close, case finalize, query send.
- **Segregation of duties** — Provider (entity-backed) can only respond to own queries; CDISpecialist cannot respond; HIMCoder cannot review.
- **Compliance pattern-matching lint** — 7 leading-phrase patterns + answer-in-question + empty indicators, gated at DRAFT→SENT.

## Step 3: Copy Shared Files — 2026-08-13T09:46:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1456_clinical_documentation_improvement/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T09:57:00.000Z

All structure confirmed. PRD generated successfully.

**PRD line count:** 261 lines
**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/workspace/PRD.md`

### Section list
- §1. Introduction (2 paragraphs: business pain-point framing + actor/program/logical-clock context)
- §2. Global Specifications & System-Wide Principles (10 subsections: RBAC, Response Structure [verbatim], Pagination, Common Resource Properties, Logical Clock, Program-Write Gating, Precision/Rounding, OCC, Nested Retrieval, Validation Order)
- §3. Business Logic & Workflows (9 subsections organized chronologically by entity lifecycle: program setup → case intake → review → query → escalation → response → final coding/reconciliation → education → denial targets/CMI)
- §4. Endpoint Definitions (1 status-code paragraph + 4-column table covering all 36 endpoints)
- §5. Error Code Catalogue (2-column table covering all 21 errors)

### Scaffold table → PRD section mapping
- `scenario` → §1 (rewritten as 2 narrative paragraphs)
- `entities` (11) → field names scattered across §2.4 (common fields), §2.1 (identity), §3.1–§3.9 (per-entity workflows)
- `state_machines` (5: CDIProgram, PatientCase, CDIReview, CDIQuery, ReconciliationEvent) → §3.1, §3.3, §3.4, §3.5, §3.7; all transitions, preconditions with paired error IDs, and side effects expressed
- `concurrency_rules` (3 OCC) → §2.8 (dedicated subsection) + reminders in §3.3, §3.4, §3.7
- `calculations` (6: case_priority_score, cmi_snapshot_computation, denial_target_miss_count, provider_education_band, non_leading_lint, review_opportunity_deltas) → §3.2, §3.9, §3.9, §3.8, §3.4, §3.6; all formulas rendered as precise natural-language prose (no pseudocode), constants embedded (1.00/1.10/1.25/1.50, 1.30/1.15/1.00, 85/70/50 bands, lint phrase list)
- `validations` (18 priorities) → §2.10 (ordered list) + trigger conditions scattered in §3 workflow narratives
- `response_envelope` → §2.2 verbatim + §2.3 (limit default 10 / min 1 / max 100 / offset 0 / created_at ascending)
- `endpoints` (36) → §4 table (Method, Path, Description, Authorized Roles)
- `errors` (21) → §5 table + referenced inline across §2 and §3
- `roles` (6) → §2.1 with explicit identity prose: `Provider` is entity-backed (X-User-ID equals Provider.id); `CDIManager`, `CDISpecialist`, `HIMCoder`, `ComplianceAuditor`, `SystemAdmin` are opaque

### Zero-Silence Rule audit (Hard Contracts)

**Contract 1 (Field-Name Coverage): PASS**
- entities[].fields + endpoint inputs + query params + path params: 102 required, 102 present, 0 missing (one field `cdi_query_id` was missed in the first pass and added to §3.6)

**Contract 2 (Rule Coverage): PASS**
- validations[] with priority ordering: 18 rules, all expressed in §2.10 ordered list
- concurrency_rules[] OCC rejections: 3/3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION 412 all named)
- state_machines[].transitions: all 19 transitions across 5 state machines expressed (from/to states, preconditions with error IDs, side effects including cascades and version increments)
- calculations[]: 6/6 fully expressed in precise business prose (reconstruction-test safe; no pseudocode; constants embedded)
- validations[] conditions: all 18 matchable to their error_id via §2.10 + §3 narratives
- endpoints[].side_effects: all expressed in the relevant §3 workflow
- entities[].fields[] structured content (defaults, ranges, enum values): all reconstructible from prose
- Sibling-branch symmetry: parallel branches (e.g., RESOLVED_CDI_PREVAILS vs RESOLVED_CODER_PREVAILS; SENT vs ESCALATED transitions; OPEN/UNDER_REVIEW/RECONCILED → FINAL_CODED) rendered with equal density

**Contract 3 (§3 Path Purity): PASS**
- 454 backtick tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos

**Withheld files respected:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, read, or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T10:20:00.000Z

Generation complete. Summary:

### Files written

**`test_helpers/`** (9 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/test_helpers/`
- `types.py` — 9 status/role enums + 11 entity TypedDicts (all carry full common fields per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (39 methods)
- `api_errors.py` — `ApiErrorId` enum (21 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_provider_education_invariants` (band checks)
- `factories.py` — one payload factory per creatable entity, input fields only, unique-seq defaults
- `constants.py` — acuity multipliers, LOS factors, education band floors, auto-event point values, min weights, clock epoch
- `test_users.py` — `TEST_USERS` for the 5 opaque roles + `make_provider_headers(provider_id)` for the entity-backed Provider role
- `fixtures.py` — 5 tiers: `create_program/policy/provider/case`, `setup_basic_scenario`, `create_and_activate_review`, `setup_sent_query`, `respond_to_query`, `setup_agreed_case`, `close_review`, `finalize_case`, `setup_finalized_case`, `drive_education_score` (splits >25 into ≤25 chunks), `setup_mismatched_finalize`
- `__init__.py` — barrel export

**`test_suite/`** (11 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/test_suite/`
- `conftest.py` + 10 test files (`test_01_program_and_case_intake` … `test_10_security_and_listing`)

### Counts
- **Total tests: 70** (all compile; no skip/skipif/xfail markers)
- **Queue A (Difficulty): 36 tests** covering 17/18 instances at ≥2 each
- **Queue B (Corner): 34 tests** covering all 26 non-stub instances at ≥1 each; all 11 `excluded_because:` stubs skipped per spec with cross-references verified resolvable

### Skipped instances (1)
- `Difficulty/priority_pair_validation_conflict/stale_version_vs_invalid_state_on_close` — the instance asserts OCC (`ERR_STALE_VERSION`) fires *before* the state check, but PRD §2.10's fixed order places the state precondition (gate 5) ahead of business rules and never states where `ERR_STALE_VERSION` sits in that order. Fails unique derivability (validation-priority silence pattern); gap left as gap.

### Stage 2 audit
- All 70 test functions carry exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, on the docstring's last line, copied verbatim from the YAML `name:` fields (AST-verified).
- All 70 tags resolve to real instances; all 11 corner stub `difficulty_instance` pointers resolve.
- Every docstring carries a `PRD §` citation, and every quoted citation of ≥6 words survives a literal (whitespace-normalized, backtick-stripped) grep of PRD.md — 0 verbatim failures.
- No test_helpers/test_suite code mentions "scaffold"; all test-suite imports from `test_helpers` resolve.

One notable design-instance correction: `priority_score_provisional_vs_residual_on_open_query` expects 71.5000, which requires working_soi=2/working_rom=2 — unreachable from a fresh case — so the test builds the state faithfully (an AGREE with weight 1.0 / soi 2 / rom 2, then a second open SENT query proposing 1.5) to reach the PRD-derived 0.5 × 1.10 × 1.30 × 100 = 71.5 rather than the naive 65.0 the recipe's literal calls would produce.

## Step 6: Generate Implementation — 2026-08-13T10:40:00.000Z

Implementation complete. Summary:

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/workspace/implementation/`)

- `start.sh` — executable launcher; guarded dependency install (`pip install` only runs if `import flask` fails), then `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, blueprint registration, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`)
- `db.py` — in-memory dicts only (11 entity collections); empty at every boot, no seeding, no disk persistence
- `errors.py` — `ApiError` + the full 21-code error catalog with PRD §5 HTTP statuses
- `response.py` — exact scaffold envelope: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp` (3-fractional-digit ISO), `response_type` object/array/error, `data`; pagination fields (`limit`/`offset`/`total_count`/`has_more`, defaults 10/1–100/0) in `meta` on lists only
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`), RBAC (403 `ERR_UNAUTHORIZED`), body/enum/int/period/pagination validators
- `clock.py` — logical epoch anchored at 2026-08-01T00:00:00Z (period 0, 1 day = 1 period); strictly-increasing entity timestamps
- `helpers.py` — record factory (id/created_at/updated_at/version=1), `touch` (version+1 on every mutation incl. cascades), program-active gate, 4-decimal half-up Decimal helpers
- `calc.py` — priority score (tiered acuity × LOS × 100, provisional/residual variants), non-leading lint (7 phrases case-insensitive + `ANSWER_IN_QUESTION` token + `NO_INDICATORS`), education score bands (85/70/50 boundaries), review opportunity deltas (cumulative AGREE sums), clock-advance sweep (one escalation step per query per advance, NO_RESPONSE at max stage), denial-target evaluation
- `serializers.py` — one serializer per entity
- `routes/` — `programs.py`, `policies.py`, `providers.py`, `cases.py`, `reviews.py`, `queries.py`, `reconciliations.py`, `targets.py`, `education.py`, `snapshots.py`, `clock_admin.py`

### Endpoint count
52 routes covering every row of the scaffold endpoint table (all CRUD, lifecycle transitions, clock advance, `_clock/set_current_utc`, sub-resource lists, OCC-protected `send`/`close`/`finalize-coding`).

### Port / binding / foreground
`app.py` reads `int(os.environ.get("PORT", "10000"))` and calls `app.run(host="0.0.0.0", port=port, threaded=True)`; `start.sh` ends with `exec python3 app.py`, so the server process stays in the foreground and inherits signals from the harness.

### Key semantics implemented
Validation order per PRD §2.10 (auth → role → existence → program gate → state → OCC → schema → business priority order); finalize-coding follows §3.7's exact precondition order (state → OCC → discharge → open-review → unresolved-query → DRG-match → denial-targets); DRG mismatch creates a `ReconciliationEvent` + case `PENDING` and rejects with 409; failed lint stores `compliant_language=false`/`lint_findings` for audit while the query stays DRAFT; auto-escalation/NO_RESPONSE/AGREE responses bump the owning review's version (per the OCC rationale in the concurrency table); CMI snapshot rounds each ratio to 4dp before subtracting, zero-case snapshots report 0.0000; denial misses evaluated against the case's finalize-period window.

### Smoke-check result
Started via `PORT=18456 bash start.sh` (fresh process, empty store confirmed). 59 assertions passed across two runs: full workflow (program → policy → provider → case → review → query → lint failure → edit → OCC 412 → send → AGREE cascade with deltas +1.0/2/1 → close → finalize → mismatch → reconcile → finalize → snapshot with lift 1.0), escalation sweep (stage 1 → 2 → NO_RESPONSE with 3/3/6-point education events), INTENSIVE_REVIEW response gating, default-policy conflict, overdue-response education events, denial-target 422s, program-write gating while SUSPENDED, and fresh-boot empty-store verification.

## Step 7: Run Tests and Iterate — 2026-08-13T11:05:00.000Z

All 8 rounds pass 76/76 with zero failures and zero errors. Clean sweep achieved.

**Iterations run:** 2 (round 1 sweep surfaced 5 deterministic failures; round 2 sweep after fixes: 76/76 × 8 rounds, all green).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/test_suite/test_01_program_and_case_intake.py` — `test_provider_education_score_is_computed_not_input`: test sent non-PRD fields (`education_score`, `education_flag`) in the create-provider payload and asserted 201 acceptance. PRD §3.1 covers the computed defaults verbatim ("New providers start with an `education_score` of 100, an `education_flag` of `NONE`, and an empty `pattern_tally_json` map") but is silent on unknown-field handling — strict-reject (the implementation's `check_known_fields` behavior) is an equally PRD-faithful reading, so the accept-extra-fields probe failed unique derivability. Per STEP 1c: kept the covered assertion (defaults on a clean create via the standard factory, now also asserting `pattern_tally_json == {}`), removed the uncovered probe.
- `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/test_suite/test_08_finalization_reconciliation.py` — `test_query_send_stale_version_after_edit`: `NameError: name 'create_query' is not defined`; added the missing `create_query` to the `test_helpers` import list. The test itself faithfully expresses PRD §2.8 OCC-on-send.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`** (both in `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/workspace/implementation/routes/queries.py`):
- `create_query` / `edit_query`: removed the draft-time `_check_provider_membership` call. PRD §3.4 attaches `ERR_PROVIDER_NOT_IN_PROGRAM` to the **send** path only, and §2.10's lint-before-membership priority ordering (asserted by `TestLintVsProviderMembershipPriority` ×2) is only reachable if a draft can exist with a cross-program recipient; §3.4 also states drafts are "freely edited". The send-time membership check is retained.
- `create_query`, `edit_query`, `cancel_query`, `create_response` (non-AGREE branch): added `compute_priority(case)` refresh. PRD §3.2 defines `priority_score` as state-dependent on the open-query set ("the provisional variant applies" when a DRAFT/SENT/ESCALATED query exists); previously only case-create / AGREE / CODER_PREVAILS / clock-advance recomputed it, leaving the score stale when queries entered or left the open set (surfaced by `test_open_sent_query_credits_proposed_weight`, expected 71.5, got 0.0). Refreshes are version-neutral system recomputations, matching the clock-sweep semantics; the AGREE branch still recomputes and bumps the case version since it rewrites working fields (PRD §3.6 + §2.4).

No test was deleted, no assertion weakened, and no PRD-required implementation check was removed.

## Step 8: Finalize PRD — 2026-08-13T11:15:00.000Z

The patch is complete and minimal. Final verification of the diff confirms exactly three edits.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 261 lines (41,921 chars); PRD_FINALIZED.md = 263 lines (43,648 chars). +2 lines (+0.77%), +1,727 chars (+4.12%). Three edits total (one paragraph inserted, one sentence revised, one sentence appended).

**Changes (one bullet per edit):**
- §2.4 — insert — new paragraph "Request bodies are closed schemas": endpoints whose body declares fields reject undeclared fields with `ERR_INVALID_REQUEST`; computed/server-managed attributes (provider's `education_score`, `education_flag`, `pattern_tally_json`) are never accepted as input; no-field action endpoints ignore the body beyond JSON-object-ness — `implementation/middleware.py:52-55` (`check_known_fields`), `implementation/routes/providers.py:34`, and the 17 strict / 10 lenient endpoint enumeration.
- §3.2 — revise — final recompute-triggers sentence now also fires "when a query on the case is drafted, edited, cancelled, responded to, or auto-closed as `NO_RESPONSE`", and pins that a recomputation unaccompanied by a write to case fields is a version-neutral system refresh (no `version`/`updated_at` bump), while AGREE / CODER_PREVAILS remain ordinary §2.4 modifications — `implementation/routes/queries.py:131,209,280,337,349`, `implementation/calc.py:45-74,225-229`, `implementation/routes/reconciliations.py:92-97`.
- §3.4 — insert — sentence after "freely edited": no recipient scrutiny at draft time; create/edit accept any `provider_id` (cross-program or unknown); `ERR_PROVIDER_NOT_IN_PROGRAM` is enforced only on the send path — `implementation/routes/queries.py:46-54,93-101,190-195,247`.

**Step 7 items with no PRD edit:** `test_08_finalization_reconciliation.py::test_query_send_stale_version_after_edit` was a pure test-code bug (missing `create_query` import); no behavioral content, no PRD change.

**Per-edit pre-edit search log:**
1. **Unknown-field strictness.** (a) Subject: handling of body fields outside an endpoint's declared set. (b) Enumerated/read: `middleware.py` `check_known_fields` + `get_json_body`; all 17 strict callers (`programs.py:44,132`; `policies.py:86,137`; `providers.py:34`; `cases.py:45,169`; `reviews.py:45,186`; `queries.py:76,167,225,296`; `reconciliations.py:75`; `targets.py:36`; `education.py:35`; `clock_admin.py:15`) and all 10 lenient body-ignoring actions (`programs.py:87,99,111,156`; `cases.py:245`; `reviews.py:104,133,154`; `queries.py:266`; `reconciliations.py:105`); `snapshots.py` confirmed read-only. (c) Initial draft said "any endpoint that accepts a request body" — falsified by the 10 lenient actions; rescoped to "endpoints whose request body declares a set of fields" and added the explicit lenient-action clause. Deliberately no claim about where in §2.10 ordering this check fires (impl placement is inconsistent: before the state gate in `edit_query`, after it in `send_query`).
2. **Priority-score recompute triggers.** (a) Subject: when `priority_score` is recomputed and whether recomputes bump case `version`. (b) Enumerated: all 8 `compute_priority` callsites (`cases.py:95`, `calc.py:229`, `queries.py:131/209/280/337/349`, `reconciliations.py:92`) plus every path changing open-query membership (draft, edit, send [membership-neutral], cancel, respond, escalate [membership-neutral], `NO_RESPONSE` at `calc.py:220`) and every case-field rewrite (AGREE `queries.py:333-338` + `touch`; CODER_PREVAILS `reconciliations.py:90-92` + `touch:97`; sweep recomputes without `touch`). (c) Added "auto-closed as `NO_RESPONSE`" to the trigger list (covered via the sweep's end-of-advance recompute) so the sentence doesn't mis-describe the score when the last open query auto-closes; scoped the version-neutrality clause with "does not accompany a write to the case's own fields" so it stays true at the AGREE/CODER_PREVAILS sites; did not claim status transitions trigger recomputation (impl does not recompute on CDI_PREVAILS — left under-determined, matching impl).
3. **Draft-time recipient scrutiny.** (a) Subject: timing of provider program-membership validation for query recipients. (b) Enumerated: grep-confirmed single `ERR_PROVIDER_NOT_IN_PROGRAM` callsite (`queries.py:247`, send only, after lint per §2.10); `create_query:93-101` and `edit_query:190-195` accept any non-empty string recipient (registered or not, any program); `create_response:301-305` uses recipient-equality (`ERR_NOT_QUERY_RECIPIENT`), a different rule; case-intake attending check (`cases.py:62-67`) uses `ERR_INVALID_REQUEST` — kept out of scope by wording tied to "a draft's recipient". (c) Wording covers both cross-program and unregistered recipients, since impl accepts both at draft time; explicitly preserves the send-path check and the §2.10 lint-before-membership order.

## Step 9: Complete PRD — 2026-08-13T11:28:30.000Z

All edits are complete and verified. The diff touches 24 paragraphs/table cells, all in-place (line count unchanged).

**Files:** `PRD_FINALIZED.md` (263 lines, 43,748 chars) → `PRD_COMPLETED.md` (263 lines, 48,242 chars). Char delta: **+4,494**. Produced `/home/ubuntu/github/CodingPRD/tasks/task_1456_clinical_documentation_improvement/workspace/PRD_COMPLETED.md`.

**Counts:** 19 ambiguity-pins, 5 mismatch-revisions (24 edited passages total; no new sections, all in-paragraph or in-table-cell).

**Mismatch revisions:**
- §2.1 — revise — mismatch — narrowed "ownership checks on any resource that references a Provider" to the single check impl performs (query `provider_id` vs `X-User-ID` on response submit); pinned that reads are never ownership-filtered — implementation/routes/queries.py:300-305 (no ownership filtering exists on any GET).
- §2.10 — revise — mismatch — reordered business-rule list to discharge (`ERR_CASE_NOT_DISCHARGED`) → open-review (`ERR_OPEN_REVIEW_EXISTS`, previously absent from the list) → unresolved-query, matching impl finalize order and §3.7 (PRD had unresolved-query before discharge) — implementation/routes/cases.py:184-204.
- §3.1 — revise — mismatch — replaced "exactly one default exists per program … introducing a second one is rejected with `ERR_DEFAULT_POLICY_CONFLICT`" with impl behavior: zero defaults allowed, setting `is_default: true` (create or update) succeeds and atomically clears siblings, only clearing the incumbent default is rejected — implementation/routes/policies.py:71-79, 109-110, 156-166.
- §3.2 — revise — mismatch — Tier 2 acuity bands reworded to "driven by the higher of `working_soi` and `working_rom`" (1.00/1.10/1.25/1.50 for 1/2/3/4); PRD's band list left (soi=1, rom=2) undefined — implementation/calc.py:19-33.
- §3.4 — revise — mismatch — "a finding for each occurrence of any leading phrase" changed to one `LEADING_PHRASE(<phrase>)` finding per distinct phrase — implementation/calc.py:95-98.

**Ambiguity pins:**
- §2.1 — insert — blank header value counts as missing — implementation/middleware.py:21.
- §2.3 — insert — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (not clamped); `has_more` = `offset + len(page) < total_count` — implementation/middleware.py:125-145, implementation/response.py:40.
- §2.4 — insert — `version` starts at 1, `updated_at` initially equals `created_at` — implementation/helpers.py:10-19.
- §2.4 — insert — missing/null/wrong-type/empty-string required fields, unresolvable body-carried FK references, and non-JSON-object bodies all rejected with `ERR_INVALID_REQUEST` (not `ERR_NOT_FOUND`) — implementation/middleware.py:42-61, implementation/helpers.py:38-49.
- §2.9 — insert — undefined paths and unsupported methods return `ERR_NOT_FOUND` (404) — implementation/app.py:49-56.
- §2.10 — insert — request-shape validation surfaces before the program-active gate on creation endpoints; uniqueness conflicts evaluated after it — implementation/routes/policies.py:96-100, providers.py:40-46, cases.py:70-76.
- §3.1 — insert — duplicate `program_code` rejected with `ERR_INVALID_REQUEST` — implementation/routes/programs.py:49-54.
- §3.1 — insert — `is_default` defaults to false when omitted; duplicate policy `name` rejected with `ERR_INVALID_REQUEST`; cleared sibling policies get a version bump — implementation/routes/policies.py:97-98, 58-68, 79.
- §3.1 — insert — duplicate `npi` per program rejected with `ERR_INVALID_REQUEST` — implementation/routes/providers.py:41-46.
- §3.2 — insert — duplicate `mrn` and cross-program `attending_provider_id` rejected with `ERR_INVALID_REQUEST` — implementation/routes/cases.py:62-76.
- §3.3 — insert — opening a draft review imposes no case-status precondition (reviewability enforced at activation) — implementation/routes/reviews.py:41-61.
- §3.3 — insert — close cascade back to `OPEN` applies only to a case still `UNDER_REVIEW`; a `RECONCILED` case stays `RECONCILED` — implementation/routes/reviews.py:209-218.
- §3.4 — insert — drafts may be created under a review in any status (`ERR_REVIEW_NOT_ACTIVE` only at send); `escalation_policy_id` must reference an existing same-program policy at draft create/edit, else `ERR_INVALID_REQUEST` — implementation/routes/queries.py:102-106, 196-204.
- §3.4 — insert — `ANSWER_IN_QUESTION` token match is exact/case-sensitive, not flanked by alphanumerics; `compliant_language`/`lint_findings` unset (null/empty) until first send attempt; failed-send findings persisted — implementation/calc.py:99-104, implementation/routes/queries.py:119-120, 236-245.
- §3.5 — insert — one evaluation per query per clock advance (multi-threshold jumps advance exactly one stage or one `NO_RESPONSE` closure); pending queries swept in creation order; child-query escalation/closure bumps owning review's version — implementation/calc.py:185-224.
- §3.7 — insert — case `version` increments on every resolution/escalation (reconciliation_status always rewritten), not only on the `RECONCILED` cascade — implementation/routes/reconciliations.py:93-98, 110-116.
- §3.8 — insert — auto-generated education events carry the triggering query as `source_query_id` and an empty `note` — implementation/calc.py:216, 223, implementation/routes/queries.py:350-353.
- §3.9 — insert — target window bounds are non-negative period indexes; `cdi_lift` = rounded `adjusted_cmi` minus rounded `unadjusted_cmi`; included cases that never finalized cannot count as `denial_target_misses` — implementation/routes/targets.py:48-49, implementation/routes/programs.py:176-177, 183-185.
- §4 — insert — `GET /api/cdi-queries/{id}/responses` returns the standard paginated array envelope (not a bare object); case-list filters are exact matches and `priority_score_min` keeps `priority_score >= value` (non-numeric rejected) — implementation/routes/queries.py:357-363, implementation/routes/cases.py:99-122.

Note: `test_helpers/` and `test_suite/` do not exist under `workspace/` (only at the task level); per instructions they were treated as non-authoritative and the walk was driven by `implementation/` directly (app, middleware, helpers, calc, clock, errors, response, serializers, and all 11 route modules).
