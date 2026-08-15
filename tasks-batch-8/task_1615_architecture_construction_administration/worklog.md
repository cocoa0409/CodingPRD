# Worklog — task_1615_architecture_construction_administration

## Step 1: Create Task Directory — 2026-08-14T01:42:00.000Z

Task directory `tasks/task_1615_architecture_construction_administration/` and `workspace/` pre-assigned by the pipeline launcher (verified present and empty). Step 1 treated as DONE per command args; no index scan performed, no other task_* directory touched.

User directive: "Generate task hard than expert level!" — elevated difficulty requirement forwarded to scaffold generation (Step 2).

## Step 2: Generate Scaffold — 2026-08-14T03:02:00.000Z

All three scaffold artifacts are generated and lint-clean.

## Deliverables (in `/home/ubuntu/github/CodingPRD/tasks/task_1615_architecture_construction_administration/`)

| File | Lines | Bytes | Content |
|---|---|---|---|
| `SCAFFOLD.yaml` | 1,724 | 94,347 | §1.0–§1.7 (no difficulty/corner keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,335 | 85,278 | `scaffold_difficulty_design:` — 22 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2,396 | 153,272 | `scaffold_corner_design:` — 67 instances (63 active + 4 `excluded_because` stubs) |

## Counts
- **Entities: 11** — CaProject (embedded SOV array), Submittal, SiteVisit, FieldReport, Rfi, ClarificationDrawing, PaymentApplication (self-referential certified chain), ChangeOrder, PunchListItem, RecordDocument, AdditionalServiceInvoice. Flat topology, all FKs reverse-reachable via filtered-list GETs.
- **State machines: 11** — four cyclic (Submittal revise/resubmit + vacate, PaymentApplication reject/resubmit + void, PunchListItem verify/reopen, RecordDocument return/resubmit), branching (Rfi answer paths, ChangeOrder recommend/override, Invoice approve/dispute), plus project lifecycle with aggregate closeout gates.
- **Endpoints: 63** (incl. `POST /ca/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default).
- **Errors: 50** — every catalog entry is referenced by a validation/transition and triggerable by at least one recipe (verified mechanically).
- **Difficulty instances: 22** (min 2 per rule): dual-variant retainage (tiered vs 50%-reduction) vs per-diem/whole-month billing; combinatorial modes a/b/c (tiered CO markup, per-line stored-materials rounding order, post-incorporation retainage re-evaluation); 3 cyclic machines; cascades of depth 3 (late review → excusable days → DRAFT invoice auto-cancel) and depth 2 (CO incorporation → invoice recompute); priority conflicts state>fiscal and temporal>referential; boundary checks on retainage threshold / horizon grace / review due-date equality; 3 cross-entity pairs; overlap rules with day-equality vs half-open-range semantics; compensating invariants on money (certify/void) and days (review/vacate).
- **Corner instances: 67** across all 9 claim-guide sections.

## Verification
- `scaffold_lint.py` verdict: **clean lint** (615 calls scanned; all endpoint/role/payload/capture/OCC checks pass; all FKs reverse-reachable).
- All formula-derived assertion literals (retainage splits, tiered markups, billable-day windows, date arithmetic) were **executed in Python and verified**; one arithmetic slip (27 vs 26 billable days) was caught and fixed.
- No sibling task directories were read; forbidden race vocabulary absent; grounds all resolve; instance names unique across both design files.

## Step 3: Copy Shared Files — 2026-08-14T03:03:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-14T03:26:00.000Z

PRD generation complete. The document is at `/home/ubuntu/github/CodingPRD/tasks/task_1615_architecture_construction_administration/workspace/PRD.md`.

## Summary

**Output**: 366 lines, ending cleanly at §5 with no audit footer. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

**Section structure** (domain-derived, per the diversity rules):
- §1 Introduction — 2 paragraphs (business context → system capabilities)
- §2 Global Specifications (11 subsections): 2.1 RBAC, 2.2 Response Structure (verbatim block, byte-identical — confirmed by string containment), 2.3 Pagination, 2.4 Logical Clock/Dates/Timestamps, 2.5 Common Resource Properties, 2.6 Monetary Precision/Rounding/Day Counting, 2.7 Validation Order & Error Precedence, 2.8 Resource Resolution & Not-Found Semantics, 2.9 OCC, 2.10 Segregation of Duties & Counterparty Ownership, 2.11 Derived Fields/Recomputation/Cascading Consistency
- §3 Business Logic (8 subsections, lifecycle-timeline strategy): project setup/SOV → submittals → visits/field reports → RFIs/drawings → payment applications → change orders → completion/punch/record docs → extended-duration billing
- §4 Endpoint table — 4 columns, all 63 scaffold endpoints present
- §5 Error catalogue — 2 columns, all 51 errors with statuses (incl. the 402 fiscal gate and the 412 OCC)

**Scaffold → PRD mapping highlights**:
- `validations[]` (25 rules) → 13-stage ordered evaluation pipeline in §2.7 plus per-endpoint ordered gate lists in §3 (certification 4-gate order, field-report 4-check order, creation 4-check order, final-completion and close ordered gates)
- `concurrency_rules[]` (2) → §2.9 with full write-endpoint + `expected_rfi_version`/`expected_project_version` + `ERR_STALE_VERSION` (412) framing, restated in §3.4/§3.6
- `calculations[]` (6) → excusable-delay credit in §3.2/§3.4 (86,400-second day, date-part comparison, zero on due date), payment certification as a pinned 9-step numbered prose list in §3.5 (chain selector with `created_at` tie-break, both retainage variants, per-line rounding before summing, provisional-vs-final divergence), change-order tiers in §3.6 (10%/7%/4% over two 5,000,000-cent tiers, per-tier rounding), billing variants + DRAFT recompute/auto-cancel/freeze in §3.8, contract position in §3.5, posture derivation (strictly-greater, equality → `NORMAL`) in §3.8
- `state_machines[]` (11) → every transition rendered with from/to states, actor, preconditions paired to error IDs, and side-effect cascades (submittal vacate reversal, drawing supersession + RFI version bump, incorporation's five-fold project mutation, void tip-only rule, period/date release semantics)

**Zero-Silence / Hard Contract results**:
- Contract 1 (Field-Name Coverage): PASS — 96 required identifiers (111 entity fields incl. nested `sov_lines`/`lines` sub-fields, 58 endpoint input/path/query identifiers incl. `posture`, `to_iso8601`, `expected_*_version`, `decision`, `outcome`), 0 missing
- Contract 2 (Rule Coverage): PASS — 66-rule / 91-probe evidence walk over priorities, OCC, side effects, applies-to scopes, field defaults/initials/null-until semantics, and sibling branches (4 review outcomes, 2 retainage modes, 2 billing methods, ACCEPT/REJECT × APPROVE/DISPUTE symmetry), 0 missing
- Contract 3 (§3 Path Purity): PASS — 563 backtick tokens in §3, 0 paths, 0 bare HTTP methods, 0 method+path combos
- Cross-checks: 51/51 error IDs in prose, 61/61 enum/state values verbatim, 4/4 roles with identity prose, 63/63 endpoint rows, no pseudocode operators or fuzzy words (all scaffold expressions translated to reconstruction-safe prose)

## Step 5: Generate Unit Tests — 2026-08-14T04:05:00.000Z

Complete. Here is the summary.

### File inventory

**`test_helpers/`** (9 files, 1595 lines):
- `types.py` — 22 status/role enums + 11 entity TypedDicts (all entities carry common fields `id/created_at/updated_at/version` per PRD 2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 63 endpoints
- `api_errors.py` — `ApiErrorId` enum (51 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + project financial invariant checker
- `factories.py` — payload factories (input fields only) for all 11 entities + action payloads
- `constants.py` — retainage/markup/billing/window/pagination constants + opaque user ids
- `test_users.py` — `TEST_USERS` shared constants + `make_<role>_headers(user_id)` builders (counterparty-gated Contractor/Owner builders take the project's recorded ids)
- `fixtures.py` — composite fixtures: project activation, performed/REPORT_ISSUED visits, certified-application chains, change-order lifecycle through INCORPORATED, record-document acceptance, substantial/final completion setups, extended-duration/horizon targeting

**`test_suite/`** (10 test files + conftest, 114 tests, 2964 lines):
- `test_01_project_setup.py` (8), `test_02_submittals.py` (12), `test_03_rfi_clarification.py` (8), `test_04_site_visits_field_reports.py` (10), `test_05_payment_applications.py` (23), `test_06_change_orders.py` (9), `test_07_punch_and_record_documents.py` (5), `test_08_project_closeout.py` (7), `test_09_invoices.py` (12), `test_10_rbac_and_envelope.py` (13), plus `conftest.py` fixture bridge

### Test counts per queue
- **Queue A (Difficulty): 22/22 instances × 2 tests = 44 tests** — every instance covered by exactly two tests
- **Queue B (Corner): 63/63 non-stub instances × ≥1 test = 70 tests** (7 instances covered by 2 tests each where setup was shared)
- **Skipped instances: none.** All 85 non-stub instances passed the PRD-first two-condition filter — every asserted rule (thresholds, rounding orders, error ids, state transitions, cascades, OCC semantics) is verbatim-covered and uniquely derived in PRD.md. The 4 `excluded_because:` stubs were correctly not translated; all four cross-references resolve to real difficulty instances.

### Stage 2 audit results
- **Tag coverage:** every one of the 85 non-stub instances has its required test count (difficulty ≥2, corner ≥1); zero missing, zero extra/unknown tags
- **Unique tags:** every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line, copied verbatim from the YAML `name:` fields — verified programmatically against both indices
- **Citation integrity (C1/C2/C3):** all 114 docstrings carry verbatim PRD quotes; automated probe confirmed every ≥10-word citation substring literally greps against PRD.md (4 initially failing citations were rewritten to full verbatim sentences)
- **Fixture integrity:** all tests build state from scratch via API calls (per-test server restart isolation respected); entity-backed counterparty calls thread `project["contractor_user_id"]`/`project["owner_user_id"]` through `make_contractor_headers`/`make_owner_headers`; fixtures use lenient `get_success_data` for setup
- **No `pytest.mark.skip`/`skipif`/`xfail`** anywhere; no "scaffold"/table-reference leakage in comments or docstrings
- **Import/collection sanity:** all 10 test modules import and execute top-level cleanly with `PYTHONPATH=.`; `pytest --collect-only` collects 114 tests with no errors

## Step 6: Generate Implementation — 2026-08-14T04:05:00.000Z

Implementation complete and verified.

### File inventory (`/home/ubuntu/github/CodingPRD/tasks/task_1615_architecture_construction_administration/workspace/implementation/`)

- `start.sh` — bash launcher, guarded `pip install` (no-op once Flask is present), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/500 handlers
- `db.py` — `LogicalClock` (default `2026-08-01T00:00:00Z`, never falls back to wall clock), UUID minting, ISO-8601-with-3-fractional-digits formatting, 11 entity stores (all empty at boot)
- `errors.py` — `ApiError` class + all 51 error-ID constants
- `response.py` — envelope helpers producing `{meta: {api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data}`; error variant carries `data.error_id`/`data.message`
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 4-role check (`FirmAdmin`/`ArchitectCA`/`Contractor`/`Owner`), per-endpoint RBAC
- `services/helpers.py` — shape validators, per-resource 404 lookups, `touch()` (updated_at + version), `paginate()` (created_at ASC, limit 1–100 default 10, offset ≥ 0)
- `services/lifecycle.py` — `require_project_active` (+`allow_substantial` for record-docs/invoices), `check_counterparty` for Contractor/Owner writes
- `services/calcs.py` — all 6 calculation rules with `Decimal`+`ROUND_HALF_UP` and the two pinned rounding orders
- `routes/{clock,projects,submittals,site_visits,field_reports,rfis,clarification_drawings,payment_applications,change_orders,punch_list_items,record_documents,invoices}.py`

### Coverage

- **Entities:** 11 / 11 (CaProject, Submittal, SiteVisit, FieldReport, Rfi, ClarificationDrawing, PaymentApplication, ChangeOrder, PunchListItem, RecordDocument, AdditionalServiceInvoice)
- **State machines:** 11 / 11 with all transitions, preconditions, and side effects (including cyclic machines: Submittal vacate/resubmit, PunchListItem reopen-from-VERIFIED with project-state gate, RecordDocument resubmit, PaymentApplication reject→resubmit and void-from-tip)
- **Endpoints:** 63 / 63 (clock set, 7 project, 6 submittal, 5 site-visit, 4 field-report, 6 rfi, 3 drawing, 7 payment-application, 6 change-order, 6 punch, 5 record-document, 7 invoice)
- **Errors:** all 51 catalog IDs wired to their exact HTTP statuses (400/402/403/404/409/412/422)
- **Calculations:** 6 / 6 — `excusable_delay_credit` (whole calendar days, floored at 0), `payment_certification` (marginal-tier vs reduction-at-halfway R(g), per-line stored rounding before sum, provisional-vs-final variants), `change_order_pricing` (10/7/4% marginal tiers at 5M/5M caps, 0 for deducts), `additional_service_billing` (PER_DIEM_PRORATED vs WHOLE_MONTH `ceil(days/30)`), `contract_position` (latest CERTIFIED gross + per-app stored sum), `ca_posture_derivation` (strict `>` comparison)
- **OCC:** both `expected_rfi_version` (drawings) and `expected_project_version` (incorporate), evaluated at stage 5 ahead of state gates, returning `ERR_STALE_VERSION` 412

### Boot verification

Verified via `start.sh` on scratch port **19991**:

1. **Boot 1:** `PORT=19991 bash start.sh &` → server ready in <2 s → `GET /ca/projects` returns `200` with empty `data: []`, `total_count: 0`, and `meta.api_request_timestamp: "2026-08-01T00:00:00.000Z"` (startup-default logical clock)
2. Created a project, then **killed the process**
3. **Boot 2 (fresh process):** same command → server came up cleanly with `data: []`, `total_count: 0`, and clock reset to `2026-08-01T00:00:00.000Z` — no carry-over state

Two end-to-end smoke suites ran against the live server (117 assertions total, all passing) covering: auth header validation, RBAC denials, counterparty 403, SOV sum/duplicate validation, submittal review/vacate with excusable-delay credit and DRAFT-invoice auto-cancel, visit date conflict, field-report SoD + issuance window (in that precedence order), RFI answer/clarification-drawing OCC + supersession + version bump, payment-application chain + TIERED_MARGINAL math + REDUCTION_AT_HALFWAY release (negative `retainage_work_cents`), certify SoD + nonconformance gate + fiscal gate, void-from-tip, change-order tiered markup + incorporation OCC + adjusted-position mutation, punch list cyclic reopen, record-document uniqueness, final-completion gates in order, invoice period adjacency/overlap, WHOLE_MONTH ceiling billing, draft freeze on issuance, and dispute/cancel release.

## Step 7: Test/Fix Iteration Loop — 2026-08-14T04:35:00.000Z

**Iterations run: 2** (each = 8 concurrent `prd-bench-local-run` rounds, `--isolation per-test-server`).

### Iteration 1 — 107/114 in every round; union of 7 failing tests, all deterministic (8/8 rounds)

Two root causes, both in the test artifact; zero implementation bugs:

1. **Fixture return-order mismatch (5 tests, test_05_payment_applications.py).** `test_helpers/fixtures.py::create_incorporated_change_order` returned `(change_order, project)` while all 4 call sites unpacked `project, _co = ...`. Downstream, the change-order dict was used as the project: two tests died on `KeyError: 'adjusted_contract_sum_cents'` (TestCertificationFiscalGate, TestCertifyRejectedAppStateBeatsFiscal), three on `HTTP 404 ERR_PROJECT_NOT_FOUND` when the CO id was used as `project_id` (TestRetainageEvalOrderAfterIncorporation ×2, TestProvisionalDiffersFromFinalAfterIncorporation ×1). Fix: swapped the fixture's return to `(project, change_order)`, matching its callers and the project-first convention of the other composite fixtures.
2. **Setup-state precondition violation (2 tests, test_08_project_closeout.py).** `TestFinalCompletionRequiresAllPunchVerified._substantial_project_with_claimed_punch` created the punch list item AFTER `achieve_substantial_completion`, but PRD §3.1 states verbatim: "Creating a submittal, site visit, RFI, payment application, change order, or punch list item requires the project to be `ACTIVE`". The implementation's `ERR_PROJECT_NOT_ACTIVE` (409) was PRD-correct. Fix: reordered the setup to raise + claim the punch item while the project is still ACTIVE, then accept record documents, then achieve substantial completion. Assertions unchanged.

No tests deleted; no assertions weakened; no implementation changes.

### Iteration 2 — 114/114 passed in all 8 of 8 rounds. CLEAN EXIT.

## Step 8: Finalize PRD — 2026-08-14T04:45:00.000Z

Analysis complete. **PRD_FINALIZED.md is identical to PRD.md — 0 edits made.**

## Summary

- **Line counts**: PRD.md 366 lines, PRD_FINALIZED.md 366 lines, 0% delta (byte-identical copy; `diff` confirms IDENTICAL).

## Per-diff-item analysis (why no edit was warranted)

**Diff item 1 — `create_incorporated_change_order` fixture return-order swap (5 tests, test_05_payment_applications.py):** Pure fixture bug, no PRD silence.
- Verified the fixture at `test_helpers/fixtures.py:264-269` now returns `(project, change_order)` and all 4 call sites (test_05 lines 189, 257, 430, 768) unpack `project, _co = ...` — consistent with the project-first convention of the other composite fixtures (e.g., `setup_project_with_certified_application` returns `(project, visit, report, application)`).
- The defect was a test-artifact unpacking convention (change-order dict used where project dict was intended, producing downstream `KeyError: 'adjusted_contract_sum_cents'` and `ERR_PROJECT_NOT_FOUND`). The PRD specifies HTTP API semantics; Python fixture return tuples are outside its scope entirely. Implementation was untouched. Nothing to pin.

**Diff item 2 — test_08 setup-state reorder (2 tests, test_08_project_closeout.py):** Test precondition violation against a rule the PRD already pins verbatim; no PRD silence, no mismatch.
- PRD §3.1 (`workspace/PRD.md:154`) states verbatim: "Creating a submittal, site visit, RFI, payment application, change order, or punch list item requires the project to be `ACTIVE` … Any of these creations attempted against a project in any other state is rejected with `ERR_PROJECT_NOT_ACTIVE` (HTTP 409)."
- Implementation conforms exactly: `implementation/routes/punch_list_items.py:37` calls `require_project_active(project)`, defined in `implementation/services/lifecycle.py:7-15`, raising `ERR_PROJECT_NOT_ACTIVE` (409) for any non-ACTIVE status.
- The fixed test (`test_08_project_closeout.py:68-92`) now raises + claims the punch item while ACTIVE, then accepts record documents, then achieves substantial completion — its own docstring quotes the same PRD §3.1 sentence as the justification. Assertions unchanged.

## Consistency sweep (NO-NEW-MISMATCH verification for the analyzed subjects)

Even though 0 edits resulted, the subagent enumerated the impl paths touching each diff item's subject to confirm the PRD's existing wording is accurate everywhere:
- **Project-ACTIVE creation gate**: `require_project_active` is used by payment_applications.py:167, change_orders.py:46, punch_list_items.py:37 (and submittals/site-visits/RFIs per the same helper import pattern); record documents and invoices use the `allow_substantial=True` variant — matching PRD §3.1's second clause verbatim.
- **Punch-item lifecycle off the Step 7 site**: claim (punch_list_items.py:88-103) and verify (106-119) carry no project-state gate (PRD §3.7 pins none for them); reopen-from-VERIFIED (137-144) requires ACTIVE or SUBSTANTIAL_COMPLETION_ACHIEVED — PRD §3.7 line 220 states this verbatim. All consistent; the PRD's existing prose correctly describes every path.

No implementation mismatches were found anywhere in the diff's blast radius, so the correct output per the task instructions is the unmodified copy and this 0-edit report.

## Step 9: PRD Completeness Scan — 2026-08-14T05:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (same content as `PRD.md`).

**Stats**
- Source: `PRD_FINALIZED.md` — 366 lines / 59,017 chars → `PRD_COMPLETED.md` — 366 lines / 60,558 chars (char-delta +1,541; 15 paragraphs touched, no sections added).
- Counts: 14 ambiguity-pins, 2 mismatch-revisions (16 changes total).

**Changes**
- §2.1 — insert — ambiguity — empty header values clarified as empty *or whitespace-only* rejected — implementation/middleware.py:18-23
- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range or non-integer rejected with `ERR_INVALID_REQUEST` 400 (not clamped); `created_at` ties broken by `id` ascending; `total_count` is post-filter pre-pagination; `has_more` = `offset + returned < total_count` — implementation/services/helpers.py:190-215
- §2.4 — insert — ambiguity — clock-set recomputes posture of all ACTIVE projects but does not mutate (no `version`/`updated_at` bump) a project whose posture is unchanged — implementation/services/calcs.py:151-157
- §2.7 stage 3 — insert — ambiguity — a request body that is not a JSON object is rejected at the body-shape stage with `ERR_INVALID_REQUEST` — implementation/middleware.py:43-54
- §2.11 — revise — mismatch — excusable-delay recompute triggers narrowed: only APPROVED/APPROVED_AS_NOTED reviews, vacates, direct answers, and drawings that move the RFI to ANSWERED recompute; REVISE_AND_RESUBMIT/REJECTED reviews and drawings on already-ANSWERED RFIs run no project recompute (impl never recomputes there) — implementation/routes/submittals.py:101-110, implementation/routes/clarification_drawings.py:69-73
- §3.1 — insert — ambiguity — activating a project not in SETUP rejected with `ERR_PROJECT_NOT_ACTIVE` (409) — implementation/routes/projects.py:167-172
- §3.2 — insert — ambiguity — submittal resubmit/vacate leave `review_notes` unchanged — implementation/routes/submittals.py:114-158
- §3.4 — revise — ambiguity — answering with `requires_clarification_drawing` true still records `answer_text`; `answered_at` stays null and no credit/recompute runs — implementation/routes/rfis.py:96-99
- §3.5 — insert — ambiguity — verification visit must belong to the same project (else `ERR_VERIFICATION_VISIT_INVALID`) — implementation/routes/payment_applications.py:84-89
- §3.5 — insert — ambiguity — resubmit excludes the resubmitted application itself from the period-ordering comparison — implementation/routes/payment_applications.py:327
- §3.6 — insert — ambiguity — originating `rfi_id` must reference an RFI on the same project (folded into `ERR_RFI_NOT_COST_IMPACT`) — implementation/routes/change_orders.py:48-58
- §3.6 — insert — ambiguity — recommend's optional `review_notes` is accepted but not persisted on the change order — implementation/routes/change_orders.py:110
- §3.7 — revise — ambiguity — final-completion gate fires `ERR_PROJECT_NOT_SUBSTANTIAL` from *any* state other than SUBSTANTIAL_COMPLETION_ACHIEVED, not only from ACTIVE — implementation/routes/projects.py:210-215
- §3.7 — insert — ambiguity — record-document resubmission leaves `review_notes` unchanged — implementation/routes/record_documents.py:110-126
- §3.8 — revise — mismatch — `horizon_end_date` when substantial completion not yet achieved is the logical-clock date *at computation time* (not frozen at invoice creation), matching draft-invoice recomputation — implementation/services/calcs.py:186-191
- §3.8 — insert — ambiguity — invoice period-overlap check is evaluated before the billable-day minimum; a period failing both reports `ERR_INVOICE_PERIOD_OVERLAP` — implementation/routes/invoices.py:43-59

Everything else in the implementation (all 40+ endpoints, role assignments, OCC handshakes, state gates and their ordering, retainage/markup/billing formulas and pinned rounding orders, recompute chains, error catalog and statuses, list filters, response envelope) was verified to already be uniquely pinned by the PRD — no changes needed.

## Pipeline Complete — 2026-08-14T05:00:00.000Z

All 9 steps finished. Final state: 114/114 tests passing in all 8 stability rounds (`--isolation per-test-server`); `workspace/PRD_COMPLETED.md` present.
