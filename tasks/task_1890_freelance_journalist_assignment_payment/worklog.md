## Step 2: Generate Scaffold — 2026-08-14T23:24:40.000Z

All checks pass. Final state:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1890_freelance_journalist_assignment_payment/`):
1. `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
2. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
3. `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **11** (Contributor, RateAgreement, Assignment, ExpenseClaim, VerificationReport, RightsPurchase, TaxDocument, Invoice, PaymentBatch, LedgerEntry, DeskConfig)
- Endpoints: **54** (includes `POST /freelance-desk/_clock/set_current_utc` with pinned startup default 2026-08-01T00:00:00Z)
- Errors: **19**; Validations: **19** (priority-ordered); Calculations: **8**; State machines: **9** (incl. a parallel `AssignmentPaymentDimension` machine); Roles: **5** (DeskAdmin, Editor, Contributor [entity_backed], FinanceUser, VerificationEditor — segregation_of_duties model); Concurrency rules: **2** (OCC on Contributor.version for agreement supersede, OCC on PaymentBatch.version for release)
- §1.8 instances: **18** (2 per rule × 9 rules — dual-variant fee-kill vs withholding-branch; combinatorial mode-(a) late-kill-halving vs mode-(c) fee-only-withholding order-pin; parallel-dimension + verification-fork state machines; depth-3 violation cascade + depth-2 batch-release cascade; state-vs-safety and referential-vs-fiscal priority pairs; bps-threshold and YTD-threshold boundaries; Assignment→Contributor and PaymentBatch→Invoice cross-entity guards; half-open rate-window vs daily-step late-fee interval semantics; batch-cancel membership and invoice-reject payment-posture compensating invariants)
- §1.9 instances: **40** total (**37** active test recipes + **3** `excluded_because` stubs), spanning entities/state_machines/calculations/validations/endpoints/errors/RBAC/cross-cutting-layers/consistency sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (721 calls scanned, 0 violations)

All formula-derived assertion literals were precomputed in code (kill tiers 22500/45000/35000/70000, withholding 25200/10500/30000/12000, net 97700/94500/79800/43000, reuse royalty 12500×2, ALL-rights uplift 35000 → 135000 claim basis, late fee 5000 at 10 days, YTD threshold 59999-vs-60000 boundary), and no forbidden concurrency vocabulary appears anywhere.

## Step 3: Copy Shared Files — 2026-08-14T23:24:45.000Z

Copied ./INSTRUCTION.md to tasks/task_1890_freelance_journalist_assignment_payment/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T23:31:00.000Z

All checks pass. Exit summary:

**PRD.md generated**: `/home/ubuntu/github/CodingPRD/tasks/task_1890_freelance_journalist_assignment_payment/workspace/PRD.md`

**Line count**: 273

**Section list**:
- 1. Introduction (3 paragraphs)
- 2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim block)
  - 2.3 Pagination
  - 2.4 Resource Identity, Timestamps, and Optimistic Concurrency
  - 2.5 The Logical Clock
  - 2.6 Monetary Precision and Rounding
  - 2.7 Hierarchical Path Validation and Cross-Aggregate Cascades
  - 2.8 Segregation of Duties
- 3. Business Logic & Workflows (11 subsections: roster/tax residency, rate agreements, commissioning, kill-fee/acceptance dual-variant, verification reports, rights/reuse/uplift, expenses, tax docs/withholding/invoice verification, batches/late fees/ledger, desk config bootstrap, validation ordering)
- 4. Endpoint Definitions (4-column table, 53 rows)
- 5. Error Code Catalogue (2-column table, 19 rows)

**Zero-silence self-check (Hard Contracts) — PASS**:
- Contract 1 Field-Name Coverage: 88 required identifiers (entity fields + endpoint inputs + query params), 88 present, 0 missing.
- Contract 2 Rule Coverage: all 11 state machines' transitions expressed (from/to/preconditions/side effects); all 8 calculations expressed in prose with pinned evaluation order and floor-division semantics; both OCC rules named with their `write_endpoint`, `expected_<parent>_version`, `ERR_STALE_VERSION`/412; all 19 validations paired with their error IDs and applies-to scopes; priority ordering explicitly narrated in §3.11; segregation-of-duties pairs, verification gate, kill-fee tiers, withholding branch order, ledger aggregation, and cascade side effects (terminate, confirm-violation, batch release/cancel) all in prose; all 59 enum values, all 36 state strings, all 5 roles, and all 19 error IDs present verbatim in backticks.
- Contract 3 §3 Path Purity: 469 backticked tokens scanned inside §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos.

(Note: the Step 4 subagent stopped once mid-task without writing PRD.md; it was resumed via message and completed successfully on the second run.)

## Step 5: Generate Unit Tests — 2026-08-15T00:10:00.000Z

Everything collects cleanly: 74 test items from 71 test functions. Final verification is complete.

### Counts
- **Queue A (Difficulty): 34 tests across 17 of 18 instances** (≥2 per instance, as required)
- **Queue B (Corner): 37 tests across all 37 non-stub instances** (≥1 per instance)
- **Total: 71 test functions (74 collected pytest items, incl. one 4-way parametrize)**
- Tag audit: **clean** — every test's docstring ends with exactly one `Design:` line resolving to a real instance; no untagged/dual-tagged/stub-pointing tests; no `skip`/`xfail`/`skipif` anywhere.
- PRD-citation sweep: **132 quoted segments, all verbatim-grep-able** against `workspace/PRD.md`.

### Instances skipped (gaps left as gaps)
- **Difficulty/cross_entity_state_dependency/batch_add_guarded_by_invoice_status** — the instance asserts `ERR_INVALID_STATE` when adding a merely-VERIFIED invoice, but PRD §3.9 verbatim says add-invoice "requires the caller to supply the `invoice_id` of an `APPROVED` invoice and requires the batch to be `OPEN` — otherwise `ERR_BATCH_NOT_OPEN`". A faithful PRD-only reader could emit either error; unique derivability fails.
- The three `excluded_because:` stubs (`error_verification_not_cleared_covered`, `stale_version_error_covered`, `contributor_terminate_cascade_covered`) were not translated, per spec. Note: their `difficulty_instance:` pointers actually resolve to queue-B corner instances, not queue-A names — a corner-design pointer quirk; coverage of the underlying rules exists via the cited corner instances, which were all generated.

### Faithful-translation repairs (asserted literals preserved, setup fixed to be PRD-derivable)
- **occ_rate_agreement_stale_version**: the recipe relied on agreement-create bumping `Contributor.version`, which the PRD never states. I advanced the contributor version via suspend+reinstate (both PRD-stated version-bumping mutations) before replaying the stale `expected_contributor_version` — same asserted rule (`ERR_STALE_VERSION` 412, no supersede on the failed write), uniquely derivable.
- **immediate_consistency_batch_totals**: the recipe omitted the VERIFIED tax document, but approval without one must fail `ERR_TAX_DOC_MISSING` per PRD §3.8. Repaired by verifying the invoice first (no doc → 24% backup → withholding 12000), then creating/verifying a W9, then approving — preserving all asserted batch totals (55000/12000/43000).
- **expense_silent_cap_and_receipt_gate**: the recipe settled a claim while the assignment was still ACCEPTED, but PRD §3.7 requires UNDER_VERIFICATION/ACCEPTED_FOR_PUBLICATION/KILLED for reimbursement. Inserted the start+submit walk before settle.
- **ledger_entry_immutability** / **batch_release_depth2_cascade**: zero-amount postings are only half-pinned by the PRD (WITHHOLDING_DEBIT is unconditional, LATE_FEE_CREDIT explicitly conditional, zero-amount EXPENSE_CREDIT ambiguous) — asserted the pinned entries as subsets rather than exact counts where ambiguous.
- **due_date/clock instants**: asserted via `startswith("2026-08-31T00:00:00")` / parsed-datetime equality, since PRD §2.4 mandates three fractional digits (".000Z"), making bare-"Z" string equality non-derivable.
- **contributor_creation_defaults_and_computed**: kept the pre-audited `version == 1` literal (benchmark-wide convention), dropped the "client-sent version ignored" sub-claim (server may legitimately reject unknown fields — not uniquely derivable).

### Files created
`test_helpers/` (9): `__init__.py`, `types.py`, `api_client.py` (38 endpoint methods under `/freelance-desk`), `api_errors.py` (19 errors + framework status-map registration), `assertions.py` (per-entity + invoice money invariants; LedgerEntry asserted version/`updated_at`-free), `factories.py`, `constants.py`, `test_users.py` (shared constants + per-instance builders incl. mandatory `make_contributor_headers` for the entity-backed Contributor role), `fixtures.py` (bootstrap/clock, contributor+agreement, editorial-pipeline walks, report clearing, expense pipeline, invoice verify/approve, batch lock/release, full paid-settlement composites — all identity-threaded).

`test_suite/` (10): `conftest.py` + `test_01_contributor_roster.py`, `test_02_rate_agreements.py`, `test_03_assignment_fees.py`, `test_04_verification_gate.py`, `test_05_expense_claims.py`, `test_06_invoices_withholding.py`, `test_07_payment_batches_ledger.py`, `test_08_rights_reuse.py`, `test_09_security_and_envelope.py`.

## Step 6: Generate Implementation — 2026-08-15T00:10:00.000Z

Implementation complete and verified. Summary:

### Files delivered

All under `/home/ubuntu/github/CodingPRD/tasks/task_1890_freelance_journalist_assignment_payment/workspace/implementation/`:

- `start.sh` — exec-based foreground launcher, binds `0.0.0.0:$PORT` (default 10000), guards `pip install` behind a `python3 -c "import flask"` check so per-test reboots never re-install
- `requirements.txt` — flask
- `app.py` — Flask entry, error handlers (ApiError, 404/405, catch-all), blueprint registration
- `server/store.py` — in-memory dicts + logical clock (starts 2026-08-01T00:00:00Z, never wall-clock); `new_entity`/`touch` helpers
- `server/errors.py`, `server/envelope.py` — scaffold's exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta)
- `server/auth.py` — `X-User-ID`/`X-User-Role` validation, 5 declared roles, role gating, ownership
- `server/util.py` — ISO8601 parse/format (3 fractional digits), body/field validators, pagination (default 10, clamp 1..100, offset ≥ 0)
- `server/serialize.py` — explicit per-entity serializers (LedgerEntry carries id/created_at only, no version/updated_at)
- `server/calc.py` — all 8 calculation rules: `assignment_fee_due` (accepted + kill variants, late-halving), `expense_reimbursement`, `withholding_computation` (pinned 4-branch order, fee-portion-only), `net_payable_allocation`, `reuse_payment`, `rights_uplift`, `late_fee` (daily step), `contributor_ytd_gross` (credit kinds only, calendar-year window, inclusive threshold)
- `server/cascade.py` — terminate cascade, CONFIRMED_VIOLATION depth-3 cascade, batch totals, batch release settlement
- 11 route modules (`routes_clock_config`, `routes_contributors`, `routes_agreements`, `routes_assignments`, `routes_verification`, `routes_expenses`, `routes_rights`, `routes_taxdocs`, `routes_invoices`, `routes_batches`, `routes_ledger`)

### Endpoints: 54/54 implemented

Every row of the §4 endpoint table, including the logical-clock test driver, with the scaffold's exact role lists and the 19-step validation priority order (auth → role → 404 → state → ownership → verification gate → SoD → rate-agreement resolvability → tax-doc mismatch → tax-doc missing → claim mismatch → receipt gate → amount → duplicate email → field shape → window → rights reuse → batch openness → OCC last).

### State machines: 9 implemented

Contributor (ACTIVE/SUSPENDED/TERMINATED + cascades), RateAgreement (create-with-supersede + OCC on `expected_contributor_version`, revoke in-flight guard), Assignment editorial dimension (DRAFT→…→UNDER_VERIFICATION with auto-created PLAGIARISM/AI_CONTENT reports in pinned order, dual kill tiers, AFP) plus the parallel payment dimension (UNINVOICED→INVOICED→PAYABLE→PAID, VOID, compensation on invoice reject), VerificationReport (threshold-inclusive flagging, SoD adjudication), ExpenseClaim (two-stage, silent cap forfeit), TaxDocument (SUBMITTED/VERIFIED/REJECTED/EXPIRED + clock sweep), Invoice (verify/approve SoD, batch settlement), PaymentBatch (OPEN/LOCKED/RELEASED/CANCELLED, lock-release SoD, `expected_batch_version` OCC, cancel compensation).

### Boot sanity check

`bash start.sh` boots in ~1s, answers a probe on `$PORT` with the correct 401 envelope and logical-clock timestamp, state wipes clean on every restart (verified: fresh boot shows 404 config + empty roster), SIGTERM terminates cleanly with port release. Three smoke suites (115 assertions: full happy path with batch settlement and ledger postings, withholding treaty/statutory/backup branches, ALL-rights uplift claim composition, terminate/violation cascades, pagination meta, all SoD and OCC rejections) all pass. No entities are seeded at startup — the store boots empty; everything is constructed via declared endpoints.

## Step 7: Run Tests and Iterate — 2026-08-15T00:30:00.000Z

All 8 rounds pass 74/74. The loop is complete.

**Iterations run:** 3 sweeps (8 parallel rounds each). Sweep 1: 43/74 (31 failures, identical across all 8 rounds). Sweep 2: 71/74 (3 deterministic failures — earlier "flaky" counts were mid-sweep progress artifacts, not true flakiness). Sweep 3: **74/74 in all 8 rounds — clean exit.**

**Tests deleted:** none. Every failing test's asserted rule was verbatim-covered by PRD and uniquely derivable; all failures were test-artifact bugs (setup/request construction), fixed per STEP 2.

**Fixes applied to `test_helpers/`:**
- `fixtures.py::setup_under_verification_cleared` — passed non-existent `plag_bps=`/`ai_bps=` kwargs to `clear_all_reports` (whose signature takes `similarity_score_bps`/`ai_probability_bps`), a TypeError that masked ~20 downstream tests. Renamed the kwargs at the call site.
- `fixtures.py::walk_assignment` — unconditionally called `offer_assignment` first, so re-walking a partially advanced assignment (ACCEPTED → UNDER_VERIFICATION, used by `setup_accepted_with_reimbursable_expense` and `TestConfirmedViolationDepth3Cascade._setup_flagged`) died with `ERR_INVALID_STATE` at offer. Made it state-aware: reads current `editorial_status` and applies only the remaining PRD transitions (offer → accept → start → submit).

**Fixes applied to `test_suite/`:**
- `test_04_verification_gate.py::test_dismissed_flag_reopens_payment_gate` — parenthesization bug: `get_success_data(resp["status"])` subscripted the `Response` instead of the parsed data; moved the `["status"]` subscript outside the call.
- `test_03_assignment_fees.py::test_kill_from_rejected_after_flag_terminal_fails` — setup relied on re-recording a result on an already-CLEARED report, a behavior PRD §3.5 does not specify (record-result is only defined as the PENDING → CLEARED/FLAGGED transition). Reached the FLAGGED precondition via PRD-specified steps instead: `setup_assignment_in_state("UNDER_VERIFICATION")` + one flagging `record_result` on the PENDING AI report (added `list_reports` import). The test's actual assertion (kill from REJECTED_AFTER_FLAG → `ERR_INVALID_STATE`, PRD §3.4/§3.11) is unchanged.
- `test_07_payment_batches_ledger.py::TestBatchCancelCompensation._setup_batched` — setup locked the batch, then exercised cancel; PRD §3.9 states verbatim "Cancellation is allowed only from `OPEN`". Rebuilt the fixture as an OPEN batch with the invoice added (no lock). Assertions unchanged.

**Fixes applied to `implementation/`:** none required. Once the test artifacts were PRD-consistent, the existing implementation (kill-fee dual variant, late halving, withholding branch order, claim reconciliation, batch release/cancel cascades, YTD threshold, ledger postings, SoD pairs, OCC) satisfied every assertion in all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-08-15T00:40:00.000Z

PRD_FINALIZED.md is complete. Summary:

**Line counts / delta:** PRD.md 273 lines → PRD_FINALIZED.md 273 lines (0% line delta; +176 characters, one sentence inserted inline into a single-line paragraph).

**Changes (1 total):**
- §3.5 — insert — added "Results land only on a `PENDING` report: recording against a report in any other status is rejected with `ERR_INVALID_STATE`." after the record-results field sentence — `implementation/server/routes_verification.py:53-54` (guard), `implementation/server/errors.py:20-21` (ERR_INVALID_STATE/409 mapping).

**Step-7 diff traceability (why the other 4 items produced no edit):**
- `fixtures.py::setup_under_verification_cleared` kwarg rename — pure helper bug; PRD §3.5 already pins the request field names `similarity_score_bps`/`ai_probability_bps` verbatim.
- `fixtures.py::walk_assignment` state-aware — pure helper bug; PRD §3.3 already pins offer's DRAFT precondition and the accept/start/submit source states.
- `test_04_verification_gate.py` parenthesization — pure test bug; no behavior question.
- `TestBatchCancelCompensation._setup_batched` — fixture violated a rule PRD §3.9 already states verbatim ("Cancellation is allowed only from `OPEN`"); impl agrees (`routes_batches.py:132-133`).

**Pre-edit search log (NO-NEW-MISMATCH RULE):**
- Edit 1 — (a) Subject: record-result state precondition — which report statuses accept a recorded result and the rejection error otherwise. (b) Impl paths enumerated and read: `routes_verification.py:47-76` record_result (the `!= "PENDING"` → `invalid_state` guard; state check sits after auth/role/not-found and before body-shape checks, consistent with §3.11's generic ordering); `routes_verification.py:79-112` adjudicate (separate FLAGGED-only endpoint, untouched by my sentence); `routes_assignments.py:181-205` submit (reports are born `PENDING` only, so record-result is the sole writer of CLEARED/FLAGGED); `routes_assignments.py:216-224` kill-from-UNDER_VERIFICATION and `:231-258` accept_for_publication (read-only over report statuses); `calc.py::sync_verification_cleared`/`verification_gate_open` (read-only); `cascade.py::reject_after_flag` (never touches reports); grep of all `STORE.verification_reports[...]` writes and report-status assignments confirmed the three mutation sites only. (c) Wording adjustment: initial draft enumerated terminal statuses ("already CLEARED or FLAGGED or adjudicated"); widened to "any other status" because the impl check is `status != "PENDING"`, which also covers DISMISSED/CONFIRMED_VIOLATION — avoiding a false narrow claim — and the sentence deliberately says nothing about adjudicate's precondition, which is outside Step 7 scope.

## Step 9: Complete PRD — 2026-08-15T00:55:00.000Z

Structure intact, all error ids valid, no new sections added. The task is complete.

**Source vs output:** `PRD_FINALIZED.md` (273 lines / 41,162 chars) → `PRD_COMPLETED.md` (277 lines / 46,524 chars); char delta +5,362. Created via `cp PRD_FINALIZED.md PRD_COMPLETED.md`, then edited only `PRD_COMPLETED.md`.

**Counts:** 24 ambiguity-pins, 2 mismatch-revisions (26 edited passages total; all in-paragraph inserts/revisions, no new sections).

**Changes:**

- §2.1 — insert — ambiguity — pinned Contributor read-side scoping: own-row reads with `ERR_NOT_OWNER` on mismatch, global assignment list narrows to caller's own — impl: server/routes_assignments.py:80-81, routes_contributors.py:84-85, and the `require_owner` calls across routes_agreements/rights/expenses/taxdocs/invoices/ledger
- §2.2 — insert — ambiguity — absent/unparseable/non-object JSON bodies treated as empty objects — impl: server/util.py:33-35
- §2.3 — revise — ambiguity — invalid `limit`/`offset` fall back to defaults and clamp (never error); `has_more` = offset + page-size < total_count; `created_at` ties break toward earlier-created — impl: server/util.py:110-127, server/envelope.py:27
- §2.5 — revise — mismatch — clock is set exactly to the supplied `to_iso8601` (no monotonicity guard; "advance" was descriptive); sweep boundary pinned (expiry exactly at now stays VERIFIED) — impl: server/routes_clock_config.py:36-41
- §2.7 — insert — ambiguity — body-carried FKs that don't resolve yield `ERR_NOT_FOUND`; unrecognized path/method yields `ERR_NOT_FOUND` (404) — impl: server/routes_assignments.py:44-45, routes_batches.py:73-74, app.py:39-46
- §3.2 — insert — ambiguity — agreement creation requires ACTIVE contributor (`ERR_INVALID_STATE`); creation bumps the parent contributor's `version`/`updated_at`; missing/non-integer `expected_contributor_version` → `ERR_INVALID_REQUEST`; per-contributor list supports `status` filter — impl: server/routes_agreements.py:36-37, 60-64, 106, 119-121
- §3.3 — revise — ambiguity — unknown body `contributor_id` → `ERR_NOT_FOUND`; `rate_agreement_id` null until offer; offer's DRAFT/contributor-ACTIVE precondition failures → `ERR_INVALID_STATE` (only the agreement-coverage failure is `ERR_NO_ACTIVE_RATE_AGREEMENT`) — impl: server/routes_assignments.py:44-47, 112-116, 58
- §3.4 — insert — ambiguity — `final_word_count` must be an integer ≥ 0, else `ERR_INVALID_REQUEST` — impl: server/routes_assignments.py:241-243
- §3.5 — insert — ambiguity — new reports born with zero scores and empty `adjudication_note`; out-of-range/missing/non-integer scores → `ERR_INVALID_REQUEST`; both scores stored regardless of kind — impl: server/routes_assignments.py:191-201, routes_verification.py:56-64
- §3.5 — revise — mismatch — adjudication `outcome` literals `DISMISSED`/`CONFIRMED_VIOLATION` with `ERR_INVALID_REQUEST` on bad outcome/empty note; cascade pinned to impl: editorial transition only from `UNDER_VERIFICATION` (cascade still runs from other states), denied claims get `reimbursable_cents` zeroed, invoices in `SUBMITTED`/`VERIFIED` flip to `VOID`, TERMINATED contributor stays TERMINATED — impl: server/routes_verification.py:94-100, server/cascade.py:23-52
- §3.6 — insert — ambiguity — reuse-royalty ledger entry carries null `invoice_id`; YTD/threshold recomputed immediately at reuse recording — impl: server/routes_rights.py:71-74
- §3.7 — insert — ambiguity — claim born with `approved_cents`/`claimed_cents`/`reimbursable_cents` null and `receipt_attached` false; `receipt_attached` defaults false when omitted — impl: server/routes_expenses.py:44-54, 121
- §3.7 — insert — ambiguity — settle `decision` literals are `REIMBURSE`/`DENY` — impl: server/routes_expenses.py:149
- §3.8 — insert — ambiguity — malformed `tin_last4` → `ERR_INVALID_REQUEST`; `treaty_country` on a W9 → `ERR_INVALID_REQUEST` — impl: server/routes_taxdocs.py:46-50
- §3.8 — insert — ambiguity — tax-doc verify `decision` literals `VERIFY`/`REJECT`; verify-time kind/residency mismatch → `ERR_TAX_DOC_MISMATCH` — impl: server/routes_taxdocs.py:107-115
- §3.8 — revise — ambiguity — invoice submission requires assignment still `UNINVOICED` (`ERR_INVALID_STATE`); non-negative-integer claim fields enforced with `ERR_INVALID_REQUEST`; new invoice born with gross/withholding/net 0, `due_date_utc` null, `payment_batch_id` null — impl: server/routes_invoices.py:40-41, 52-56, 64-71
- §3.8 — insert — ambiguity — invoice verify applies only to a `SUBMITTED` invoice whose assignment remains `ACCEPTED_FOR_PUBLICATION`/`KILLED`, else `ERR_INVALID_STATE` — impl: server/routes_invoices.py:130-134
- §3.8 — insert — ambiguity — latest-valid-document tie-breaking extended: further ties past `created_at` break toward the later-created document — impl: server/calc.py:74
- §3.9 — revise — ambiguity — add-invoice: invoice must be APPROVED and unattached to any batch (`ERR_BATCH_NOT_OPEN` otherwise); unknown `invoice_id` → `ERR_NOT_FOUND`; all batch mutation endpoints return the updated `PaymentBatch` — impl: server/routes_batches.py:62-82
- §3.9 — insert — ambiguity — cancel from non-OPEN → `ERR_INVALID_STATE` — impl: server/routes_batches.py:132-133
- §3.9 — insert — ambiguity — release: missing/non-integer `expected_batch_version` → `ERR_INVALID_REQUEST` — impl: server/routes_batches.py:114-118
- §3.9 — revise — ambiguity — late-fee days = whole 24-hour periods (floor of second difference / 86400), clamped at zero — impl: server/calc.py:103-106
- §3.9 — revise — ambiguity — "every covered expense claim" pinned to claims in `REIMBURSABLE` status — impl: server/cascade.py:96-99
- §3.10 — insert — ambiguity — reading DeskConfig before initialization yields `ERR_NOT_FOUND` — impl: server/routes_clock_config.py:77-78
- §3.11 — revise — mismatch — add-invoice batch-openness check carved out: evaluated immediately after the batch's path existence, before body validation (impl checks `ERR_BATCH_NOT_OPEN` ahead of `invoice_id` field-shape) — impl: server/routes_batches.py:66-71
- §4 — insert — ambiguity — list-filter semantics: exact match; `reportable_threshold_crossed` parses case-insensitive `true`/`false`, other values apply no filtering — impl: server/routes_contributors.py:61-66

All calculations, state machines, endpoint/role table, error catalogue, and OCC semantics were verified to already match the implementation; no behavioral inventions were added.
