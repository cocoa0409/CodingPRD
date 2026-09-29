# Worklog — task_2464_scholarly_journal_peer_review_publishing

## Step 1: Create task directory — 2026-09-02T20:38:01.695Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2464_scholarly_journal_peer_review_publishing/` and its `workspace/` subdirectory. Index 2464 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created (concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-02T22:51:01.967Z

All three scaffold artifacts for task 2464 are complete and lint-clean.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2464_scholarly_journal_peer_review_publishing/`
- `SCAFFOLD.yaml` (3112 lines, 13 top-level keys, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2081 lines, single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (6489 lines, single key `scaffold_corner_design`)

**Lint verdict** (`skills/prd-bench-scaffold-generator/scaffold_lint.py`): `VERDICT: clean lint` — 59 endpoints declared, 14 entities, 18 §1.8 instances, 81 §1.9 recipe instances, 1452 calls scanned; all calls conform to §1.5 and all §1.1 FKs have reverse-reachability.

**Scaffold surface**
- Complexity profile: archetype peer-review/publishing pipeline; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `selector_policy`; topology `flat`; state-machine shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`.
- 14 entities: Journal, Editor, Author, Reviewer, Manuscript, IntegrityScreening, EditorAssignment, ReviewInvitation, Review, Decision, Appeal, EthicsCase, ProductionJob, APCInvoice.
- 7 state machines (Manuscript with revision + appeal loops, EditorAssignment, ReviewInvitation, Appeal, EthicsCase, ProductionJob with two parallel stage dimensions and a proof loop, APCInvoice) + 3 OCC concurrency rules (manuscript, production_job).
- 12 calculations (reviewer reliability with rolling/lifetime variants, consensus index with UNWEIGHTED vs RELIABILITY_WEIGHTED variants, APC net amount waterfall, surcharge-relief brackets, two selector policies, two interval-occupancy calcs, reminder/lateness sweep, integrity rollup, embargo projection, metrics rollup).
- 35 validation rules in a strict priority ladder (with two documented carve-outs from rule 13), 61 error ids, 6 roles (SystemAdmin, EditorInChief, HandlingEditor, Reviewer, Author, ProductionStaff), 59 endpoints including `POST /_clock/set_current_utc` and `POST /_ops/run-reminder-sweep`.

**Design instance counts**
- §1.8: 18 instances (9 hard-reasoning rules × 2), all with full `test_recipe`s.
- §1.9: 96 instances across all nine guide sections — entities 12, state_machines 14, calculations 9, validations 20, endpoints 7, errors 22, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1 — of which 81 carry full recipes and 15 are `excluded_because` stubs citing existing §1.8 instances by name.

**Verified coverage properties:** all 61 declared error ids are triggered by at least one §1.8/§1.9 instance; every claim_type is a row from `references/claim-extraction-guide.md` (normalized to snake_case); all 114 instance names are unique across both design files; every stub's cited §1.8 name exists. Only three of 59 endpoints (`GET /decisions`, `GET /editors`, `GET /manuscripts/{id}/apc-invoices`) appear solely in assert prose rather than as executed calls.

## Step 3: Copy shared files — 2026-09-02T22:51:20.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2464_scholarly_journal_peer_review_publishing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T23:06:00.000Z

PRD complete at `/home/ubuntu/github/CodingPRD/tasks/task_2464_scholarly_journal_peer_review_publishing/workspace/PRD.md` — 501 lines, ~104 KB, ending cleanly on the last row of the §5 error table (no audit footer, no truncation).

**Section list**

- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC · 2.2 API Response Structure (verbatim contract, byte-identical) · 2.3 Pagination · 2.4 Record Identity, Timestamps and the Editorial Clock · 2.5 Version Guards on Editorial Writes · 2.6 Segregation of Editorial Duties · 2.7 Fee Arithmetic, Percentages and Rounding · 2.8 Conserved Ledgers and Monotone Audit Counters · 2.9 Cascades, Parallel Stage Dimensions and Scoped Reads · 2.10 Order of Rejection (all 35 priorities as a ladder)
- §3 Business Logic & Workflows — 3.1 Journal & editorial community · 3.2 Submission intake, formatting, licensing · 3.3 Integrity screening & ethics escalation · 3.4 Editor assignment, conflict, recusal, desk screening · 3.5 Reviewer invitation, occupancy windows, reminder sweep · 3.6 Review submission, lateness, reliability · 3.7 Decisions, revision rounds, appeals · 3.8 Ethics cases, correction, retraction · 3.9 APC pricing & settlement · 3.10 Production, deposit, publication, journal metrics
- §4 Endpoint Definitions — 4-column table, all 59 endpoints
- §5 Error Code Catalogue — 2-column table, all 61 errors

**Field coverage check:**
- `entities[].fields`: 140 required, 140 present, 0 missing
- `endpoints[].input`: 93 required (optionality markers stripped), 93 present, 0 missing
- path params: 3 required, 3 present, 0 missing
- `query_params`: 0 declared in scaffold (filters described in §2.3)
- error IDs: 61 required, 61 present, 0 missing
- Status: **PASS**

**Rule coverage check:**
- `validations[]` with priority: 35 checked, 35 expressed in prose (§2.10 ladder + per-workflow prose), 0 missing
- `concurrency_rules[]` OCC rejections: 3 checked, 3 expressed with write endpoint + `expected_manuscript_version` / `expected_production_job_version` + error ID + 412, 0 missing
- `state_machines[].transitions`: 45 checked, 45 fully expressed with preconditions and side effects, 0 missing
- `calculations[]`: 12 checked, 12 fully expressed, 0 missing
- `validations[]` conditions → error ID pairing: 35 checked, 35 matchable, 0 missing
- `endpoints[].side_effects` / `applies_to`: 113 side-effect entries and 35 `applies_to` scopes, all expressed, 0 missing
- field-level structured content (enums, defaults, min/max, computed rules): reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (advance/desk-reject; accept/decline; uphold/overturn; pay/waive/cancel; the three ethics resolutions; proof approve/reject; the two ethics fork branches; the two invitation-withdrawal sources) — equal prose density, 0 asymmetric
- Status: **PASS**

**Path purity check (§3 only):** 1008 backtick tokens scanned; tokens containing `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0. Status: **PASS**

**Notes for the worklog**
- The two design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.
- Two internal scaffold inconsistencies were resolved and should be flagged upstream: (1) DOI composition — the entity field definition uses `doi_prefix` + `/` + `issue_label` + `.` + zero-padded `journal_sequence_number`, while the publication side-effect describes a journal-name slug instead of `issue_label`; I followed the field definition, which two of three sources agree with. (2) `Journal.max_proof_rounds` mentions `ERR_PROOF_ROUNDS_EXHAUSTED`, which is not in the error catalogue; the PRD uses only the catalogued `ERR_PROOF_ROUND_LIMIT_REACHED`.
- §2 was given 10 subsections and §3 10 subsections rather than the 5–9 guideline, because 14 entities, 45 transitions and 12 calculations could not be covered losslessly at lower granularity. All path-bearing content (OCC endpoints, `applies_to` scopes) was deliberately placed in §2 so §3 stays path-pure.

**Orchestrator truncation audit (per invocation guard):** verified independently — `PRD.md` is 500 lines / 104330 bytes, tail ends on a complete `| \`ERR_WAIVER_NOT_ALLOWED\` | 409 |` table row; §5 contains exactly 61 error rows and §4 exactly 59 endpoint rows, matching the scaffold counts. No truncation; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T02:20:00.000Z

Queue B complete. Both queues are generated, compiled, and audited.

## Files written

**`test_helpers/`** (infrastructure, 8 modules + `__init__.py`, ~2540 lines): `api_client.py`, `api_errors.py` (`ApiErrorId` + error→status map), `types.py`, `constants.py`, `test_users.py` (per-role header builders), `factories.py`, `assertions.py`, `fixtures.py` (~90 atomic helpers + 25 composite `setup_*` world builders). Only change this session: added `fixtures.list_assignments(manuscript_id, state=None)`.

**`test_suite/`**: 30 test files, 218 test functions (~229 collected, one 12-way parametrize), plus `conftest.py`.

## Test counts

| | tests | instances |
|---|---|---|
| Queue A (Difficulty §1.8) | 52 in 9 files | 18/18 covered, all >=2 tests |
| Queue B (Corner §1.9) | 166 in 21 files | 78/81 non-stub covered |

Queue B by section: entities 23, state_machines 20, calculations 23, validations 34, endpoints 13, errors 41, rbac 11, cross_cutting 8, consistency_model 3. All 15 `excluded_because:` stubs emitted zero tests; each stub's `difficulty_instance:` cross-reference was verified to resolve to a queue-A instance that is in fact covered.

## Audit result: 0 problems
Machine-checked across all 30 files: every test has exactly one `Design:` line; all 218 tags resolve to a real non-stub instance in the correct queue/section; no tag points at a stub; every `PRD:` citation is a verbatim substring of `workspace/PRD.md`; every file has >=5 tests; no duplicate test function names; no `mark.skip`/`xfail`; no `response.json()["error"]`; no occurrence of "scaffold" or section-sign in generated code. `python3 -m compileall` clean. Nothing under `workspace/implementation/` was read or written; no pytest run.

## Instances skipped (3, all queue B, all the same PRD defect class)

The PRD pairs a "any other state" error with a "closed/settled/adjudicated row" error for the same trigger, so rejection-ladder rung 13-before-14 and the workflow prose give different error ids — outcome not uniquely derivable:

1. `Corner/state_machines/second_decline_on_declined_invitation_returns_invalid_invitation_state` — `ERR_INVALID_INVITATION_STATE` vs `ERR_TERMINAL_STATE_LOCKED` for a replayed decline.
2. `Corner/errors/second_adjudication_of_an_upheld_appeal_rejected` — `ERR_INVALID_APPEAL_STATE` vs `ERR_TERMINAL_STATE_LOCKED`; an Appeal's only non-`FILED` states are `UPHELD`/`OVERTURNED`, so both clauses describe the identical trigger.
3. `Corner/errors/settlement_of_an_already_paid_invoice_rejected` — `ERR_INVALID_INVOICE_STATE` vs `ERR_TERMINAL_STATE_LOCKED`; every non-`ISSUED` status is a settled invoice. Side effect: that recipe's conserved-ledger no-write claim on a double settlement is untested.

## PRD issues worth carrying into the worklog

- **Zero-total invoice contradiction.** 3.9 says a `total_due_cents == 0` invoice "needs no settlement at all" and its issuance advances clearance to `FEE_CLEARED`, but 3.10 requires that no invoice remain at `ISSUED` for deposit/publication — and nothing moves a zero invoice off `ISSUED`. Tests assert the explicit 3.9 outcome and waive the zero invoice before publishing so they hold under either reading.
- **`opened_by` on a manual ethics case** is `"MANUAL"` per 3.8, not the opening editor's id (a recipe asserted the id); tests follow the PRD.
- **Undeclared/forged body fields** (`status`, `doi`, `id`, `version`) have no stated treatment (ignore vs `ERR_INVALID_REQUEST`), so those fields were dropped and only server-derived values are asserted.
- **`ERR_LICENSE_LOCKED` vs `ERR_TERMINAL_STATE_LOCKED`** on a licence change against a `DESK_REJECTED` manuscript: the specific 3.2 rule was followed; two tests in `test_state_error_editorial_transitions.py` are the ones to revisit if the implementation reads rung 14 generically.
- **Appeal window** at exactly 30 days is ambiguous ("within 30 days"), so only day 31 is asserted.

### Orchestrator note on Step 6
The first Step 6 subagent (implementation generator) died to an upstream API timeout before writing any file. It was relaunched with an added instruction to write modules to disk incrementally and an explicit prohibition on reading `test_suite/` / `test_helpers/`, which by then existed on disk. No partial implementation output from the failed attempt existed, so nothing needed cleaning up.

## Step 6: Generate implementation — 2026-09-03T04:20:00.000Z

The implementation is complete and verified end to end.

## Files written

`workspace/implementation/` — 19 Python modules + `start.sh` + `requirements.txt`, 3,610 lines total.

**Core (this session's final module: `app.py`)**
- `app.py` — Flask factory, blueprint registration, `ApiError` -> error envelope, `HTTPException` -> `ERR_INVALID_REQUEST` (404 unknown route, 405 method, 400 bad JSON), `PORT` env default 10000, `use_reloader=False`.
- `db.py` — the only state: plain dicts on a `Store` singleton. Logical clock pinned at `2026-08-01T00:00:00Z`, forward-only. `stamp_new` / `touch` (per-request dedupe so one row bumps `version` once per request).
- `errors.py` (61 ids + statuses), `response.py` (envelope), `validate.py` (body/enum/int/date readers, pagination), `auth.py` (`authorise`, `require_editor_journal`), `calc.py` (exact `Fraction` money + staged round-half-up, reliability, consensus, both selectors, slot conflict, embargo, metrics), `services.py` (cascades), `serializers.py`.
- `routes/` — 9 blueprints: registry, manuscripts, assignments, invitations, decisions, ethics, fees, production, ops.

**All 59 declared endpoints implemented, zero extra** (diffed programmatically against the SCAFFOLD endpoint table). All 14 entity payloads diffed field-for-field against the entity table — no missing, no extra fields, `common_fields: false` honoured for IntegrityScreening / Review / Decision.

## Verification

Five scripted suites against a freshly booted server each time: happy path to publication; revision rounds -> `ERR_REVISION_LIMIT_REACHED`; reject -> appeal -> overturn (replacement editor selected) and uphold; ethics OPEN->INVESTIGATION->(fork)->COMMITTEE_REVIEW-> correction then retraction (4-link cascade, `published_article_count -= 1`); integrity BLOCK auto-case + desk reject; recusal cascade with `replaced_assignment_id` chain; invitation decline/withdraw/selector/reminder/expiry sweep; APC pricing (verified `base -> waiver -> institutional -> surcharge relief bracket` arithmetic by hand against both relief tiers); typeset slot conflict with changeover buffer; proof-round limit; deposit ordering; `ERR_UNPAID_APC_INVOICE`; OCC 412s on both guards; pagination bounds; parent mismatch; role/identity/authorisation gates. Every assertion passes. Fresh boot returns empty lists for all collections — nothing seeded — and no `open()`/sqlite/file/tmp usage anywhere in the tree.

## Ambiguities resolved

- **Scaffold-vs-PRD conflicts, PRD wins:** the DOI uses the job's `issue_label` (scaffold prose said "journal name slug"), and the error id is `ERR_PROOF_ROUND_LIMIT_REACHED` (scaffold prose said `ERR_PROOF_ROUNDS_EXHAUSTED`).
- **`to_state`/`to_stage` enums accept every declared state**, so a real-but-unreachable state yields `ERR_INVALID_ETHICS_CASE_STATE`/`ERR_INVALID_PRODUCTION_STAGE` (409) per PRD 3.9, not a 400. This was the one bug the suites caught and it is fixed.
- **Terminal beats invalid-state.** The ladder lists rule 13 before 14, but read literally rule 14 would be unreachable (no transition is declared from a terminal state), so `ERR_TERMINAL_STATE_LOCKED` is returned for terminal subjects and `ERR_INVALID_*_STATE` otherwise.
- **Revisions replace only supplied fields** — PRD 3.10 says "optionally a replacement `data_availability_statement`", so omitting it keeps the stored value.
- **Read-time computation** for `formatting_status`, `integrity_status`, `submitted_review_count` and journal metrics; counters/flags stay event-driven. This is what makes `ERR_DATA_AVAILABILITY_REQUIRED` reachable — PRD 2.5 says config is read live by every gate, so PATCHing `requires_data_availability_statement` after a manuscript reaches `DECISION_PENDING` blocks its ACCEPT (verified).
- **Ordering calls inside the ladder:** interval (8) precedes OCC/terminal/`ERR_ASSIGNMENT_NOT_ACTIVE`; duplicate key (10) precedes terminal (14) on screenings; `ERR_LICENSE_LOCKED` beats the generic terminal lock for the four locked statuses; explicitly inviting a RETIRED reviewer is `ERR_REVIEWER_CONFLICT`; ethics-resolution segregation is skipped for auto-opened `SCREENING_CASCADE` cases (no opener to conflict with); publication's ethics hold covers a case of any severity while decisions/invoices only block on HIGH.

## Step 7: Run tests and iterate — 2026-09-03T01:24:49.696Z

Done — clean 8-round parallel sweep, **229/229 passing in all 8 rounds** (no flakiness, no reaping; sweep log has zero `Terminated`).

## Iterations run
2. Iteration 1 exposed 5 failures, identical in all 8 rounds (no flakiness — one shared root cause). Iteration 2 was clean.

## Failing set (union across 8 rounds)
- `test_pricing_apc_waterfall_edges.py::test_zero_total_invoice_clears_the_fee_dimension_at_issuance` — `clearance_stage == 'LICENSE_PENDING'`, expected `FEE_CLEARED`
- `test_production_dimensions_and_retraction.py::test_zero_total_invoice_clears_fees_while_the_content_dimension_stands_still` — same
- `test_production_dimensions_and_retraction.py::test_retraction_{resolution_closes_the_case_and_retracts_the_article,terminates_both_dimensions_of_the_production_job,flips_the_two_journal_article_counters}` — all three died in setup with `ERR_DEPOSIT_NOT_READY`, downstream of the same defect

## Tests deleted
None. Every asserted rule is verbatim in PRD.md and uniquely derivable:
- 3.9: *"An invoice whose `total_due_cents` computes to 0 — a green self-archived paper with no surcharges, or a fully waived one — needs no settlement at all, and its issuance immediately advances the manuscript's production job on the clearance dimension, `LICENSE_PENDING -> FEE_CLEARED`."*
- 3.8 retraction four-link cascade (`RETRACTED`/`retracted_at`, job -> `TERMINATED`/`WITHDRAWN`/`WITHDRAWN`, `published_article_count -= 1` / `retracted_article_count += 1`).

## Fixes applied to `implementation/`
- `workspace/implementation/services.py` — `advance_fee_clearance()` gained an `ignore_invoice_id` parameter. It previously refused to advance whenever *any* invoice of the manuscript sat at `ISSUED`, which included the zero-total invoice being issued in that very request, so the 3.9 "immediately advances" rule was unreachable. Another still-`ISSUED` non-zero invoice continues to hold clearance back.
- `workspace/implementation/routes/fees.py` — the zero-total branch of invoice issuance now passes `ignore_invoice_id=row["id"]`.

## Fixes applied to `test_helpers/`
- `test_helpers/fixtures.py`, `setup_ready_to_publish()` — the fixture paid the invoice only when `total_due_cents > 0` and otherwise left it at `ISSUED`, which violates PRD 2.10 rule 28 (*"Publication requires that the manuscript carry no invoice still in status `ISSUED`"*). A zero invoice also cannot be paid (3.9 `PAY` requires `total_due_cents` greater than 0), so the fixture now **waives** it. This makes the setup PRD-faithful rather than relaxing the implementation's rule-28 gate; the retraction tests' assertions are untouched.

## Notable PRD tension (resolved in favour of the specific rule, worth flagging upstream)
3.9's zero-total sentence says issuance advances clearance *"immediately"* and deliberately omits the *"once no invoice of that manuscript remains at status `ISSUED`"* qualifier that the same section attaches to `PAY`/`WAIVE`. But nothing in the PRD ever moves a zero-total invoice off `ISSUED`, so rule 28 makes such a manuscript unpublishable until someone waives it. Both layers now follow the literal text: the implementation honours the 3.9 "immediately", and the fixture satisfies rule 28 by waiving. Third-party storage/seeding checks are clean (in-memory dicts only; no `open`/sqlite/`/tmp`).

### Orchestrator verification of the Step 7 sweep
Independently re-read all eight `workspace/implementation/results.{1..8}.json`: every file exists, each reports `passed=229 total=229`, all written within a 3-second window at 01:22:57–01:22:59 UTC, and `workspace/sweep.log` contains zero occurrences of `Terminated`. The clean-sweep claim is confirmed against the artifacts, not taken on report. Step 8 is NOT skipped (2 implementation fixes + 1 test_helpers fix).

## Step 8: Finalize PRD — 2026-09-03T01:27:30.000Z

Done. `PRD_FINALIZED.md` written.

## Size
- `PRD.md`: 500 lines / `PRD_FINALIZED.md`: 500 lines — 0 line delta (0.00%); 2 of 500 lines revised in place (0.4% of lines touched).

## Changes
- **3.9 (fee clearance on zero-total issuance)** — *revise* — appended two clauses to the "`total_due_cents` computes to 0" sentence: the immediate `LICENSE_PENDING -> FEE_CLEARED` advance disregards the zero-total invoice's *own* `ISSUED` status, is still held back by any **other** invoice of the manuscript at `ISSUED`, and is a silent no-op (issuance still succeeding) when there is no production job yet or the job's clearance dimension already left `LICENSE_PENDING`; plus that the zero-total invoice is *not* settled by this — it stays `ISSUED` with `settled_at` absent and still counts against publication under 2.10 rule 28 until waived or cancelled. — `implementation/routes/fees.py:68-70`, `implementation/services.py:259-277`
- **3.10 (clearance dimension)** — *revise* — the flat universal "requires that no invoice of the manuscript remains at status `ISSUED`" gained the single carve-out for a zero-total invoice at the moment of its own issuance, cross-referencing 3.9. Without this the section directly contradicts the implementation's zero-total path. — `implementation/services.py:270-274`

## Pre-edit search log

**Edit 1 — 3.9 zero-total clearance advance**
- (a) Subject: every precondition and side effect of the `LICENSE_PENDING -> FEE_CLEARED` transition, and the lifecycle status of a zero-total invoice.
- (b) Paths enumerated (grepped `clearance_stage|ISSUED|FEE_CLEARED|advance_fee_clearance` across all of `implementation/`, then read each hit): `services.py:259-277` (sole writer of `FEE_CLEARED`; guards = job exists, job at `LICENSE_PENDING`, no `ISSUED` invoice other than `ignore_invoice_id`); `routes/fees.py:68-70` (zero-total issuance, the Step 7 site); `routes/fees.py:124-125` (PAY/WAIVE settlement — *no* `ignore_invoice_id`, so the zero invoice does hold clearance back there); `routes/fees.py:91-113` (PAY refuses `total<=0`; WAIVE has no total check; CANCEL blocked once a job exists past `LICENSE_PENDING`); `routes/fees.py:58-60` (invoice born `ISSUED`, `settled_at` None, never auto-settled anywhere); `calc.py:165-166` + `routes/production.py:163-166` (publication's rule-28 gate counts *any* `ISSUED` invoice, zero-total included); `routes/production.py:131-141` (deposit requires `FEE_CLEARED`); `services.py:220-234` + `services.py:54` (retraction drives clearance to `WITHDRAWN`; terminal-job guard).
- (c) Adjustments made: (i) scoped the carve-out to "its **own** `ISSUED` status ... at the moment of its own issuance" rather than "a zero-total invoice never blocks clearance" — the latter would be false at `routes/fees.py:125`, where a still-`ISSUED` zero invoice blocks another invoice's PAY/WAIVE from clearing; (ii) added the no-job / already-past-`LICENSE_PENDING` no-op clause with "issuance still succeeding" so no reader infers a new error; (iii) wrote "waived or cancelled" (not "settled" or "paid") because PAY is unreachable for a zero total, and left cancellation's own precondition to the existing 3.9 `CANCEL` paragraph rather than restating it.

**Edit 2 — 3.10 fee-clearance precondition**
- (a) Subject: the same `LICENSE_PENDING -> FEE_CLEARED` precondition, as restated in the production section.
- (b) Paths enumerated: `services.py:259-277` (the single gate); both callsites `routes/fees.py:69` and `routes/fees.py:125`; `routes/production.py:123-145` (deposit path, which only reads the resulting `FEE_CLEARED`, never re-tests invoices); plus a PRD-side sweep of every other `ISSUED` claim (2.8 receivable-ledger invariant, 2.10 rule 28, 3.9 line 344, 3.10 publication paragraph) to confirm none of them needed the same carve-out — all four are exactly what the implementation does and were left verbatim.
- (c) Adjustment made: phrased as a narrow exception delegating to 3.9 instead of restating the mechanism, so the sentence keeps describing the PAY/WAIVE case (the common path) as a strict "no invoice at `ISSUED`" requirement, which is what `routes/fees.py:125` enforces.

No edits were made for the retraction-cascade failures: those died only in fixture setup, the cascade in `services.py:220-234` already matches 3.8 link for link (the `max(0, ...)` clamp on `published_article_count` is unreachable given retraction requires `PUBLISHED`/`CORRECTED`), and the `test_helpers/fixtures.py` change was a fixture bug against PRD 2.10 rule 28, not a PRD silence.

## Step 9: Complete PRD — 2026-09-03T01:54:59.511Z

`PRD_COMPLETED.md` is finished.

## Totals
- Source `workspace/PRD_FINALIZED.md`: 500 lines / 105,016 chars
- `workspace/PRD_COMPLETED.md`: 500 lines / 115,595 chars (delta **+10,579 chars**, 0 new lines, 0 new sections)
- 41 paragraphs touched, 56 discrete changes: **43 ambiguity-pins**, **13 mismatch-revisions**

## Changes

2.1 — insert — ambiguity — opaque roles (`SystemAdmin`, `ProductionStaff`) never resolve `X-User-ID`, so the header may be absent — `auth.py:30-44`
2.1 — insert — ambiguity — `role_level` check fires immediately after identity resolution; journal check applies only to the eight manuscript-scoped editorial writes and runs after FK resolution but before body-shape validation; ethics endpoints exempt — `auth.py:52-64`, `routes/ethics.py:48-63`
2.4 — revise — mismatch — `created_at` ties are routine under the logical clock and are broken by insertion order, never by `id` — `db.py:120-126`
2.5 — insert — ambiguity — unparseable `current_utc` -> `ERR_INVALID_REQUEST` (400); success returns HTTP 200 with a single-field `{current_utc}` object — `routes/ops.py:16-26`
2.9 — revise — mismatch — `version` advances by exactly 1 even when one request rewrites a row twice; recomputing either manuscript flag to its existing value is not a mutation; `created_at` uniqueness claim replaced by insertion-order tiebreak — `db.py:100-117`, `services.py:69-75`, `services.py:107-114`
2.10 r7 — insert — ambiguity — undeclared body fields and query parameters are ignored, not rejected — `validate.py:30-40`
2.10 r11 — revise — mismatch — ownership rule also guards proof approval, the licensing change, the conflict declaration and a handling editor's self-recusal — `routes/production.py:103`, `routes/manuscripts.py:196`, `routes/assignments.py:90`, `routes/assignments.py:120`
2.10 r13 — insert — mismatch — the terminal test (r14) is evaluated ahead of the declared-transition test on every action endpoint — `services.py:23-55` call sites
2.10 r19 — revise — mismatch — rule covers assignment creation only (and also bars an editor holding a `RECUSED` assignment); the conflict declaration itself never raises it — `calc.py` selector + `routes/assignments.py:46-60`
3.1 — insert — ambiguity — `subject_areas` elements are stored verbatim, only non-emptiness checked — `validate.py:150-166`
3.1 — revise — mismatch — journal PATCH advances `version` unconditionally; `doi_prefix`, `name`, `subject_areas` are silently ignored — `routes/registry.py:96-118`
3.2 — insert — ambiguity — `supersedes_manuscript_id`: 404 vs `ERR_INVALID_MANUSCRIPT_STATE`, tested after ownership; cross-journal supersession allowed — `routes/manuscripts.py:60-80`
3.2 — insert — ambiguity — `journal_sequence_number` allocation mutates the journal, advancing its `version` — `routes/manuscripts.py:85-92`
3.2 — insert — ambiguity — `embargo_requested` is a gate input only, never persisted; the licensing write fires even when the licence is unchanged — `routes/manuscripts.py:196-206`
3.3 — insert — ambiguity — the measurement a scan type does not use is stored/returned as null; screening is status-ungated except for the two terminal statuses, tested after the duplicate-key check — `routes/manuscripts.py:120-140`
3.3 — insert — ambiguity — the cascade-opened case has server-generated `description` and records no opening editor, so segregation never fires on it — `routes/manuscripts.py:146-157`
3.4 — insert — ambiguity — a new assignment's four optional fields all begin absent — `services.py:148-157`
3.4 — insert — ambiguity — explicit-editor tests run conflict/recusal -> subject-area -> workload; journal, `role_level` and `ACTIVE` bind the selector pool only — `routes/assignments.py:46-70`
3.4 — insert/revise — ambiguity+mismatch — conflict declaration: non-holder -> `ERR_NOT_RESOURCE_OWNER`; `handling_gap_flag` clearing only advances `version` when it was true; missing `conflict_type` -> `ERR_INVALID_REQUEST` (400) applied after the state gates; response body is the original assignment — `routes/assignments.py:88-109`
3.4 — insert — ambiguity — recusal: non-holder -> `ERR_NOT_RESOURCE_OWNER`; `reason` not persisted; manuscript terminal test runs after the assignment gates — `routes/assignments.py:113-131`
3.4 — insert — ambiguity — screening-decision `note` validated but not persisted — `routes/manuscripts.py:220`
3.4 — insert — ambiguity — screening-decision gate order: integrity rollup -> formatting -> journal scope — `routes/manuscripts.py:224-236`
3.5 — insert — ambiguity — invitation creation reads no manuscript status beyond the terminal bar — `routes/invitations.py:50-70`
3.5 — insert — ambiguity — an explicitly named `RETIRED` reviewer -> `ERR_REVIEWER_CONFLICT` — `routes/invitations.py:74-80`
3.5 — revise — mismatch — only the `ACTIVE`-assignment holder may withdraw (`ERR_ASSIGNMENT_NOT_ACTIVE`); `reason` not persisted; withdrawal never recomputes the shortfall flag — `routes/invitations.py:219-240`
3.5 — revise — mismatch — `review_shortfall_flag` is stored, recomputed at only three moments and cleared outright on entry to review; no other event revisits it — `services.py:107-114`, `routes/manuscripts.py:163-166`
3.6 — revise — mismatch — manuscript `version` advances on every review submission, not only when the auto-transition fires — `routes/invitations.py:215`
3.7 — insert — ambiguity — decision issuance requires no `ACTIVE` assignment; any handling editor of the journal may issue — `routes/decisions.py:24-42`
3.7 — revise — mismatch — `response_letter` required but persisted nowhere; an omitted `data_availability_statement` leaves the stored one — `routes/manuscripts.py:255-272`
3.8 — insert — ambiguity — `to_state` accepts all seven declared states (unreachable -> 409, unknown string -> 400) — `routes/ethics.py:21-93`
3.8 — insert — ambiguity — opener id is internal-only, absent from the case representation; segregation is checked before the terminal and state gates — `routes/ethics.py:108-115`, `services.py:215`
3.9 — revise — mismatch — all three settlement actions share one role set (no per-action split); every settlement also advances the journal's `version` — `routes/fees.py:76`, `routes/fees.py:118-122`
3.9 — insert — ambiguity — omitted `amount_cents` on `PAY` -> `ERR_INVALID_REQUEST`, not a mismatch error — `routes/fees.py:92-93`
3.9 — insert — ambiguity — blank/whitespace `waiver_reason` also -> `ERR_WAIVER_NOT_ALLOWED` — `routes/fees.py:98-99`
3.10 — insert — ambiguity — slot booking reads no manuscript status; a later content stage -> `ERR_INVALID_PRODUCTION_STAGE` — `routes/production.py:56-57`
3.10 — insert — ambiguity — content-advance enum accepts `TERMINATED`; gate order = undeclared step -> `ERR_SLOT_NOT_BOOKED` -> `ERR_INVALID_MANUSCRIPT_STATE` — `routes/production.py:77-85`
3.10 — insert — ambiguity — `proof_comments` validated but not persisted; proof approval also requires `IN_PRODUCTION`, tested after the stage gate — `routes/production.py:100`, `routes/production.py:109-110`
3.10 — insert — ambiguity — a second deposit at `DEPOSIT_CONFIRMED` -> `ERR_INVALID_PRODUCTION_STAGE`, tested ahead of the `FEE_CLEARED` gate; wrong manuscript status -> `ERR_DEPOSIT_NOT_READY` — `routes/production.py:132-139`
3.10 — revise — mismatch — publication gate order = stage join -> manuscript status -> ethics -> unpaid invoice (PRD had invoice first) — `routes/production.py:156-166`
3.10 — insert — ambiguity — supplied `issue_label` is stored on the job; a never-supplied label mints an empty DOI segment (`10.5555/.0001`) — `routes/production.py:169-182`
3.10 — insert — ambiguity — the publication response body is the production job, not the manuscript — `routes/production.py:191`
3.10 — insert — ambiguity — odd-count `median_days_to_first_decision` is emitted as a whole day count, not a 2dp value — `calc.py:627-631`

Method note: the source file was copied, not rewritten; only `PRD_COMPLETED.md` was edited; no `SCAFFOLD*.yaml` or `worklog.md` was read; tests were consulted only as cross-reference, never as authority.

### Orchestrator close-out verification
`workspace/PRD_COMPLETED.md` verified independently: 500 lines / 115,595 bytes, 28 headings, all 61 error rows present, tail ends on the complete `| \`ERR_WAIVER_NOT_ALLOWED\` | 409 |` row — no truncation. Workspace contains INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (with results.1..8.json all 229/229) and sweep.log. Pipeline complete through Step 9.
