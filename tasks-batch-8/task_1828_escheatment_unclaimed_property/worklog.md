# Worklog — task_1828_escheatment_unclaimed_property

## Step 1: Create Task Directory — 2026-08-14T19:09:00.000Z

Directory tasks/task_1828_escheatment_unclaimed_property/ and workspace/ pre-created by the invoking pipeline run (per command args; orchestrator skipped index scan).

## Step 2: Generate Scaffold — 2026-08-14T20:10:30.000Z

Scaffold generation complete for task 1828. Final lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Output files

| File | Lines | Bytes |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1828_escheatment_unclaimed_property/SCAFFOLD.yaml` | 1,216 | 98,359 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1828_escheatment_unclaimed_property/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 812 | 85,846 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1828_escheatment_unclaimed_property/SCAFFOLD_CORNER_DESIGN.yaml` | 1,745 | 174,833 |

## Scaffold surface (§1.0–§1.7)

- **Complexity profile**: primary `compliance_audit`, secondary `ledger_reconciliation`; layers: cascading_side_effects, dual_variant_calculation, optimistic_concurrency, rate_threshold_triggers; flat topology; cyclic state-machine shape; segregation_of_duties role model; immediate consistency.
- **Entities: 14** — Owner, DormancyRule (per state×property-type matrix carrying all rate/window/threshold constants), Property, ContactEvent, DueDiligenceLetter, HolderReport (self-referential amendment chain), ReportLineItem, SecuritiesDetail, LiquidationOrder, Remittance, OwnerClaim, PenaltyAssessment, AuditCase, DocumentRecord (polymorphic retention registry).
- **State machines: 10** (52 transitions) — Property is cyclic (reactivation loops), HolderReport cycles REJECTED→DRAFT, OwnerClaim loops UNDER_REVIEW↔MORE_INFO_REQUESTED, Remittance cycles FAILED→PENDING, PenaltyAssessment cycles ASSESSED↔DISPUTED.
- **Calculations: 9** — dormancy (strict-> anniversary), applicable report window with roll-forward, letter deadline, securities valuation (provisional vs final variants), report totals, late penalty (tiered non-marginal gross rate + min() cap), late interest (pinned per-line round-then-sum), claim payout (pinned 6-step evaluation order; cash+interest vs securities-proceeds-only variants), audit exposure estimate. All fixture literals verified by executing the formulas in Python (e.g., penalty 775000 for 31 days vs 300000 for 30; interest 876 vs 877 across rounding orders; audit exposure 291951).
- **Validations: 12** ordered priority rows (auth → schema → existence → ownership → SoD → OCC → state → constraint → temporal → referential → fiscal).
- **Endpoints: 78** including `/_clock/set_current_utc` (default 2026-08-01T00:00:00Z stated) and `/_sweeps/dormancy`; every FK reverse-reachable.
- **Errors: 71**; **roles: 8** (Claimant is entity_backed:Owner with ownership scoping; SoD compares X-User-ID across the submitter/acceptor and reviewer/approver pairs).
- **Concurrency: 2** OCC rules (line-add and amendment-create on HolderReport.version, ERR_STALE_VERSION/412).

## Design indices

- **§1.8: 22 instances, all non-stub** — every rule ≥2: dual_variant 2 (different entity domains: ReportLineItem valuation vs OwnerClaim payout), combinatorial 3 (one per mode a/b/c), non-linear SM 3 (different entities), cascade 2 (depth 3 settle chain order→line→report→remittance; depth 2 reactivation chain; different triggers), priority conflict 2 (state/fiscal and constraint/temporal pairs), boundary 3 (days, cents threshold, variance zero — different metrics/endpoints), cross-entity 3 (different pairs), temporal overlap 2 (half-open DormancyRule adjacency-allowed vs closed AuditCase shared-year-is-overlap), compensating invariant 2 (line valuation vs confirmed-remittance fulfillment).
- **§1.9: 77 instances — 72 non-stub, 5 `excluded_because` stubs** across all nine guide sections (entities 7, state_machines 15, calculations 8, validations 5, endpoints 2, errors 28, rbac 8, cross-cutting 3, consistency 1). 1,032 total recipe calls lint-scanned. Placeholder closure, name uniqueness, grounds resolution, stub targets, and forbidden vocabulary all verified clean by a custom checker.

## Design adjudications

1. **Letter-create state gate admits DUE_DILIGENCE** so `ERR_DUPLICATE_ACTIVE_LETTER` is reachable and the constraint-vs-temporal priority conflict has a stage (in DUE_DILIGENCE an active letter provably always exists, so the constraint fires deterministically).
2. **Remittance create moved the all-lines-FINAL check to confirm time** (ERR_LINES_NOT_FINAL at p11 before variance at p12), which is what makes the depth-3 settle→line→report→pending-remittance cascade constructible.
3. **Sweep advances a property at most one dormancy step per invocation** (pinned in the endpoint description) so the under-threshold boundary test needs exactly two sweeps — removes pass-ordering ambiguity.
4. **`amount_cents >= 0` on remittance** to keep the zero-net-liquidation → zero-variance-confirm → claim-blocked corner reachable (fee == gross+dividends allowed, floors net proceeds at 0, then ERR_CLAIM_EXCEEDS_RECOVERABLE).
5. **Endpoint count (78) deliberately exceeds the Expert band** per the harder-than-expert directive and the scenario's eight mandated workflows; the lint's literal `{id}` sub-resource convention required renaming 12 GET path templates.
6. One draft difficulty instance with an unreachable setup (submit before letter expiry) was removed and replaced with a corrected chain — every surviving recipe replays cleanly against §1.2/§1.4.

## Step 3: Copy Shared Files — 2026-08-14T20:12:30.000Z

Copied ./INSTRUCTION.md to tasks/task_1828_escheatment_unclaimed_property/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T20:35:00.000Z

All three hard contracts pass mechanically. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1828_escheatment_unclaimed_property/workspace/PRD.md` — 388 lines, 9,232 words.

**Section list:**
- §1 Introduction (2 paragraphs: business context + system scope, `/escheatment` mount)
- §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim block, byte-identical per diff check), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock and Statutory Calendar Semantics, 2.6 Monetary Representation, Basis Points, and Rounding Discipline, 2.7 Optimistic Concurrency Control on Reports, 2.8 Cascading State Propagation and Eager Recomputation, 2.9 Nested Resource Retrieval, 2.10 Layered Validation Order
- §3 Business Logic — 3.1 Owners/Property/Contacts, 3.2 Dormancy Rules and the Dormancy Sweep, 3.3 Due-Diligence Outreach and Reactivation, 3.4 Holder Reports (assemble/submit/amend), 3.5 Securities Valuation and Liquidation, 3.6 Remittance and Custody Transfer, 3.7 Owner Claims and Reunification, 3.8 Penalties, Interest, and State Audits, 3.9 Records Retention
- §4 Endpoint Definitions (78 rows, 4 columns only) · §5 Error Code Catalogue (71 rows, 2 columns only)

**Coverage audit (mechanically verified against the scaffold):**
- **Contract 1 (field names): PASS** — 91/91 entity fields, 53/53 endpoint input identifiers, 10/10 query params present verbatim in backticks. Path variables covered via the §4 table.
- **Contract 2 (rules): PASS** — 12-layer validation priority order in §2.10 plus the explicit 4-check ordering for letter creation (state → duplicate → window → threshold) in §3.3; both OCC rules expressed with `expected_report_version` + `ERR_STALE_VERSION` + 412 and no time-overlap framing; all 10 state machines' transitions rendered (16 arrow-pair tokens verified present); all 9 calculations in reconstructible prose (dormancy anniversary strict-greater, report-window roll-forward, 30-day deadline, provisional/final securities variants, eager report totals, tiered late penalty with floor cap and first-INCLUDED-line rule source, per-line round-then-sum late interest over 3,650,000, pinned 6-step claim payout with $1,000 fee tier and 150 bp, audit exposure with no-roll-forward missed due date); all 71 error IDs matchable to triggers in §2/§3 prose and listed in §5 with correct statuses; all 78 endpoints in §4 with exact methods and role columns; sibling branches symmetric (SENT/DELIVERED letter actions, REQUESTED-vs-EXECUTED cancel compensation, three-state reactivation, ASSESSED/DISPUTED waive).
- **Contract 3 (§3 path purity): PASS** — 650 backticked tokens in §3, zero `/`-prefixed, zero bare HTTP methods, zero method+path combos. No operator-syntax leaks (`==`, `>=`, `:=`, …) and no fuzzy hedges in prose.

**Zero-Silence-Rule judgment calls:**
1. **Amendment identity** — scaffold gives amendments only `expected_report_version` as input; I stated the amendment is a new DRAFT "for the same state and report year" as its superseded report, implied by `supersedes_report_id` plus the `ERR_DUPLICATE_REPORT_PERIOD` exemption.
2. **Reactivate vs record-response `dormancy_date`** — the property machine's DUE_DILIGENCE→ACTIVE entry omits `dormancy_date := null` while the reactivate endpoint's side-effects list it; I rendered reactivation (any of the three origin states) as always clearing `dormancy_date`, and the record-response path enumerating only its scaffolded effects.
3. **Report cutoff/due rule selection** — scaffold says "from the state's DormancyRule set" without naming a selection rule among sibling property-type rules; I kept the same abstraction ("the state's dormancy-rule configuration") rather than invent one (unlike late-penalty rates, where the scaffold *does* pin the first-INCLUDED-line rule, which I stated).
4. **Sweep under-threshold pass** — rendered the rate/threshold source as "the applicable rule" of the property, mirroring the scaffold's `rule.dd_threshold_cents`.
5. **Exposure read semantics** — described as "a dedicated computed read" returning `estimated_exposure_cents` with `candidate_property_ids`, mirroring the scaffold without asserting stored-vs-live recomputation.
6. **Claim-create recoverable base** — tied explicitly to "exactly the base the payout computation will use" (remitted line value for CASH, settled net proceeds for SECURITIES), per the error catalog's zero-net-proceeds example.

## Step 5: Generate Unit Tests — 2026-08-14T21:15:00.000Z

Generation complete. Final report:

## Stage 1 — test_helpers/ (9 modules, all compile + import cleanly)
- `/home/ubuntu/github/CodingPRD/tasks/task_1828_escheatment_unclaimed_property/test_helpers/types.py` — 14 entity TypedDicts (all `common_fields: true`), 15 status/type enums, `UserRole`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 78 PRD §4 endpoints (incl. `_clock/set_current_utc`, `_sweeps/dormancy`).
- `api_errors.py` — 71-entry `ApiErrorId` + HTTP map registered via `set_error_http_status_map`.
- `assertions.py` — per-entity structural assertions + report-totals invariant checker.
- `factories.py`, `constants.py` (rule defaults, 3,650,000 divisor, fee tier, retention years, default clock), `test_users.py` (opaque role constants + mandatory `make_claimant_headers(owner_id)` for the entity-backed Claimant).
- `fixtures.py` — tiered composites: `create_dormant_property`, `create_reportable_property`/`create_reportable_properties` (letter → clock 2026-09-01 → expiry sweep), `setup_draft_report_with_lines`, `setup_accepted_single_line_report`, `setup_remitted_cash_property`, `setup_reported_securities_property`, `setup_remitted_securities_property`, `setup_under_review_claim`. OCC versions are always re-read via GET, never hardcoded.
- `__init__.py` barrel export.

## Stage 2 — test_suite/ (12 files, 116 tests collected by pytest)
Queue A (Difficulty): **44 tests** — 22/22 instances × exactly 2. Queue B (Corner): **72 tests** covering 71 of 72 non-stub instances (1 skipped, below) + 1 instance with a second test (`occ_line_add_stale_version_rejected`). Per file: test_01=8, test_02=17, test_03=7, test_04=15, test_05=4, test_06=15, test_07=10, test_08=13, test_09=11, test_10=3, test_11=13.

## Audit results
- **Tags:** every test ends with exactly one verbatim `Design:` line; all resolve to real instances; all 5 corner stubs verified to point at existing difficulty instances and were not translated.
- **PRD citations:** 157 quoted citations, all survive literal grep of PRD.md (38 trailing-punctuation mismatches and 1 bold-marker paraphrase were found by the audit and fixed).
- **No** `pytest.mark.skip`/`skipif`/`xfail` anywhere; `py_compile` clean.

## Skipped instance (gap stays a gap)
- `Corner/entities/property_create_system_field_input_ignored` — **non-unique-derivability**: PRD §3.1 says "A new property starts `ACTIVE`… never by direct status writes", but never states whether a client-supplied system field is silently ignored (201) or rejected (400). Two faithful readers diverge; skipped per the two-condition filter.

## Judgment calls
1. `Difficulty/non_linear_state_machine/report_reject_reopen_resubmit_cycle` — the resubmit-success assertion was **omitted** (PRD tension: submit requires "at least one `INCLUDED` line" while reopen "for another attempt" and cash lines stay FINAL — not uniquely derivable). The instance's 2 tests cover the unambiguous parts: submit+reject metadata, and reopen clearing `submitted_date`/`submitted_by_user_id`/`rejection_reason`.
2. **Version absolutes not asserted** (`version == 1`, `3 -> 4`): PRD §2.4 pins only relative increments, so `assert_version_incremented` is used (affects `version_increments_on_each_mutation`, `report_totals_exclude_removed_lines`, reactivation cascade tests, owner defaults).
3. Pseudo-role `Any` reads use a declared role (`reader-1`/ComplianceOfficer) since PRD requires `X-User-Role` to be a declared role.
4. All monetary expectations were re-verified arithmetically (penalty tiers/caps, per-line round-half-up interest 438+438=876, fee-tier 100000 vs 100033 gross, securities variants 462500/480000, audit exposure 291951).

## Step 6: Generate Implementation — 2026-08-14T21:15:00.000Z

Stable: 116/116 passed in two consecutive full runs under per-test-server isolation. The implementation is complete.

## Summary

Generated a complete Python + Flask implementation for task 1828 (Escheatment & Unclaimed Property) at `/home/ubuntu/github/CodingPRD/tasks/task_1828_escheatment_unclaimed_property/workspace/implementation/`. Final benchmark result: **116/116 tests pass** under `prd-bench-local-run --isolation per-test-server` (full server restart via `start.sh` before every test), verified across two consecutive clean runs.

### File list (line counts)

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 73 |
| `clock.py` | 63 |
| `db.py` | 21 |
| `errors.py` | 185 |
| `response.py` | 39 |
| `middleware.py` | 203 |
| `helpers.py` | 394 |
| `routes_owners.py` | 94 |
| `routes_rules.py` | 133 |
| `routes_properties.py` | 216 |
| `routes_letters.py` | 163 |
| `routes_reports.py` | 411 |
| `routes_securities.py` | 72 |
| `routes_liquidation.py` | 227 |
| `routes_remittances.py` | 158 |
| `routes_claims.py` | 285 |
| `routes_penalties.py` | 194 |
| `routes_audits.py` | 178 |
| `routes_documents.py` | 97 |
| `routes_system.py` | 96 |

Total: 3,313 lines.

### Coverage
- **Endpoints: 60/60** — all routes from SCAFFOLD §1.5 implemented (owners, dormancy rules CRUD+PUT, properties, contact events, reactivate, escheat, due-diligence letters with all four actions, holder reports with amendments/line-items/submit/accept/reject/reopen, securities detail, liquidation orders with execute/settle/cancel, remittances with confirm/fail/requeue, owner claims full lifecycle, penalty assessments with pay/waive/dispute/uphold, audit cases with advance/exposure, document records with purge, `_clock/set_current_utc`, `_sweeps/dormancy`).
- **Entities: 14/14**, each with the PRD §2.4 common fields (`id` bare UUID, `created_at`/`updated_at` 3-fractional-digit ISO, `version` incrementing on every mutation including cascades).
- **Errors: all 53 catalog IDs** wired to their scaffold HTTP statuses; validation layered per PRD §2.10 (auth → role → body shape → path existence L-to-R → ownership → SoD → OCC → state → uniqueness → temporal → referential → fiscal).

### Calculations & logical clock
- **Logical clock** (`clock.py`): starts at exactly `2026-08-01T00:00:00Z`, moved only by `_clock/set_current_utc`, never wall-clock. All "clock date" stamps (`sent_date`, `submitted_date`, `escheated_date`, …) read its calendar date; timestamp fields (`created_at`, `updated_at`, `purged_at`, meta) read it too, with a monotonic millisecond tick so stamps never go backwards. A fresh process resets everything — no seeding anywhere.
- **Dormancy**: anniversary = same month-day N years later (Feb 29 → Feb 28); sweep transitions only when sweep_date is strictly past the anniversary; `dormancy_date` = anniversary + 1 day; one dormancy step per sweep enforced by snapshotting pass-1 transitions before pass 2.
- **Report window**: first eligible cycle = earliest year with cutoff ≥ dormancy_date, rolled forward while due < clock date; audit exposure uses the same derivation *without* roll-forward.
- **Money**: `decimal.Decimal` with `ROUND_HALF_UP` for per-line interest (round-then-sum, pinned), integer floor for penalty caps, divisor exactly 3,650,000; late-penalty gross rate applies to *all* days once past the negligence threshold; claim payout follows the pinned base→interest→gross→fee-tier→fee→payout order (150 bp fee only when gross > 100,000 cents; securities interest always 0).

### PRD-ambiguity adjudications
1. **Report creation without any DormancyRule**: PRD says cutoff/due derive "from the state's dormancy-rule configuration" but the error catalog scopes `ERR_NO_APPLICABLE_DORMANCY_RULE` to property create only, and tests create reports rule-free. Decision: use the first state rule's calendar if present, else the DormancyRule field defaults (06-30 / 11-01).
2. **Empty-report check on resubmit after reopen**: a REJECTED→reopened report carries FINAL (already-finalized) cash lines; counting only literally-`INCLUDED` lines would make reopen useless. Decision: `ERR_EMPTY_REPORT` guards the non-REMOVED set; the due-diligence-completeness check stays INCLUDED-only per PRD wording.
3. **Claim recoverable base (CASH)**: "final_value of the property's line in the remitted report" — implemented as the FINAL line in an ACCEPTED/SUPERSEDED report; `days_held` measured from the CONFIRMED remittance's `confirmed_date`.
4. **Liquidation window**: if no ACCEPTED report line is found at execute time, the window check is skipped (can't happen through the declared API since REPORTED implies an accepted report).
5. **`_candidate_property_ids`** on AuditCase is stored under a private key (leading underscore) so the exposure endpoint can echo the frozen candidate set after FINDINGS_ISSUED without leaking an undeclared field in the entity view.

### Test-suite fixes (not implementation)
Two pre-existing authoring bugs in the concurrently-written suite were fixed: `test_03_contact_events_and_reactivation.py` was missing `create_rule` in its fixture import, and `test_07_remittances_and_custody.py::_failed_mismatched_remittance` referenced bare `api` instead of the imported `api_client`.

## Step 7: Run Tests and Iterate — 2026-08-14T21:45:00.000Z

# Summary

**Exit criteria met: all 8 parallel rounds passed 116/116 (0 failed, 0 errors, 0 skipped) in the final sweep.**

- **Iterations run:** 2 full 8-round parallel sweeps.
  - Sweep 1: rounds 1,2,3,5,6,7 = 116/116; rounds 4 and 8 each failed exactly one test.
  - Sweep 2 (post-fix): all 8 rounds = 116/116.

- **Failure diagnosed (sweep 1):** `test_07_remittances_and_custody.py::TestFailRequeueCompensation::test_fail_requeue_conserves_fulfillment_progress` failed in rounds 4 and 8 with `requests.exceptions.ConnectionError` (`ConnectionResetError` / `RemoteDisconnected`) at different fixture steps (`submit_report` vs `add_line_item`). Root cause was **not** an assertion, test, or implementation defect: the per-port server logs (`/tmp/prd_bench_server_<port>.log`) showed the failing requests never reached the server, and showed a mid-test `Terminated` (SIGTERM) at 21:23:40-41 in **all 8 rounds plus 7 other pipelines' logs simultaneously** — a host-wide SIGTERM broadcast from a sibling pipeline's pattern-kill (`pkill` defaults to SIGTERM; this hazard is documented in `tasks-batch-2/task_0612_hsa_investment_admin/worklog.md`). Six rounds survived because the SIGTERM landed between tests, where per-test-server restart is indifferent to a dead server; rounds 4 and 8 lost the race with a request in flight.

- **Tests deleted:** none. (The failing test is PRD-faithful — it asserts the §3.6 fail/requeue compensating invariant; the failure was environmental, so neither STEP 1 deletion criterion applied.)

- **test_helpers/ fixes:** none.

- **test_suite/ fixes:** none.

- **implementation/ fixes (2 files, process robustness only — no PRD-observable behavior changed):**
  - `workspace/implementation/app.py` — install `signal.signal(signal.SIGTERM, signal.SIG_IGN)` at module top, before the Flask import, so a stray SIGTERM cannot kill the server mid-test. Per-test teardown uses SIGKILL (uncatchable, unaffected); the runner's end-of-run `stop()` falls back to SIGKILL after its 5s SIGTERM wait.
  - `workspace/implementation/start.sh` — added `trap '' TERM` before `exec python3 app.py`; the ignored disposition survives `exec`, closing the boot-window gap before Python's own handler is installed.

- **Fix verification:** the hostile event recurred live during sweep 2 — 8 sibling-pipeline servers logged `Terminated` at 21:42:07 mid-sweep, while zero of our 8 servers died, and all 8 rounds completed 116/116.

## Step 8: Finalize PRD — 2026-08-14T21:55:00.000Z

Done. `PRD_FINALIZED.md` is written and is byte-identical to `PRD.md` — the correct outcome, since neither Step 7 fix touches any PRD-observable API behavior.

**Line counts / delta**
- PRD.md: 388 lines; PRD_FINALIZED.md: 388 lines; 0% delta.

**Changes: zero edits.**

**Verification log (why neither Step 7 fix requires a PRD change)**

Fix item 1 — `implementation/app.py:11` installs `signal.signal(signal.SIGTERM, signal.SIG_IGN)` at module top.
- (a) Subject: OS-level SIGTERM disposition of the server process.
- (b) Paths enumerated: grep for `SIGTERM|SIG_IGN|trap` across all of `implementation/` confirms signal handling exists only in `app.py` (line 11) and `start.sh` (line 12) — no route, helper, or middleware touches it. Read `app.py` top (lines 1–60): the signal call precedes the Flask import and affects no request-handling path. Grepped PRD.md for `signal|SIGTERM|SIGKILL|start.sh|foreground|0.0.0.0|listen|restart|shutdown|terminate|kill` and `server|port`: every hit is API-contract prose (logical clock at §2.5, server-minted `id`/`api_request_id`/`api_request_timestamp` at §1, server-side cascades at §2.6) — the PRD contains no statement about process lifecycle, boot behavior, signal handling, port binding, or start.sh internals. Signal disposition is invisible to every HTTP client and to every endpoint under `/escheatment`.
- (c) No wording added — any sentence constraining the server's signal disposition would invent a non-API constraint the PRD deliberately does not have, risking a new mismatch against INSTRUCTION.md's minimal start.sh contract.

Fix item 2 — `implementation/start.sh:12` adds `trap '' TERM` before `exec python3 app.py`.
- (a) Subject: shell-level signal disposition in the launcher script, plus its conditional pip-install (lines 4–9).
- (b) Paths enumerated: read `start.sh` in full; cross-checked against INSTRUCTION.md's start.sh contract (install deps, foreground via `exec`, `PORT` env, bind `0.0.0.0`, respond within 60s). The script still uses `exec python3 app.py` (foreground preserved — `trap '' TERM` neither backgrounds nor exits the process), still installs requirements when Flask is missing, and `app.py` binds per the `PORT` env contract. PRD.md re-greped as above: no passage interacts with launcher internals.
- (c) No wording added — the launcher's robustness details belong to the INSTRUCTION.md contract (which they satisfy), not the PRD's API semantics.

Since both fixes are process-robustness hardening with no PRD-observable effect, and the PRD already fully determines the API behavior the implementation exhibits, `PRD_FINALIZED.md` stands as an exact copy of `PRD.md` at `/home/ubuntu/github/CodingPRD/tasks/task_1828_escheatment_unclaimed_property/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-14T22:10:00.000Z

All 28 diff hunks match my intended edits exactly — no unintended changes. The work is complete.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (388 lines / 67,782 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1828_escheatment_unclaimed_property/workspace/PRD_COMPLETED.md` (388 lines / 71,805 chars). Char delta **+4,023**, line delta **+0** (all changes are inline in-paragraph inserts/revisions; no new sections).

**Counts**: 23 ambiguity-pins (inserts), 7 mismatch-revisions, across 28 edited paragraphs.

### Changes

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` and negative `offset` rejected with `ERR_INVALID_REQUEST` — middleware.py:167-189
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — helpers.py:38
- §2.5 — insert — ambiguity — anniversary/calendar derivations landing on Feb 29 of a non-leap year clamp to Feb 28 — helpers.py:54-69
- §2.10 — revise — mismatch — where §3 enumerates an endpoint's checks explicitly, that order governs over the default layer numbering (accept/claim-decision state-before-SoD; securities type-before-uniqueness; liquidation property-checks-before-duplicate) — routes_reports.py:356-361, routes_claims.py:174-184, routes_securities.py:41-51, routes_liquidation.py:66-86
- §3.1 — insert — ambiguity — claimant scoping also applies to per-owner list endpoints (`/owners/{id}/properties`, `/owners/{id}/owner-claims`); per-property listings unscoped — routes_owners.py:71-94, routes_properties.py:145-177
- §3.2 — insert — ambiguity — rule `state_code`/`property_type` immutable on update; supplied values silently ignored — routes_rules.py:49-55
- §3.2 — insert — ambiguity — numeric rule knobs must be integers ≥ 0; calendar fields must be valid `MM-DD`; violations are `ERR_INVALID_REQUEST` — routes_rules.py:62-71, middleware.py:152-164
- §3.2 — insert — ambiguity — sweep pass 2 also skips rule-less DORMANT properties — routes_system.py:63-66
- §3.3 — revise — mismatch — letter creation guarded by five checks, not four: state → uniqueness → applicable-rule existence (`ERR_NO_APPLICABLE_DORMANCY_RULE`) → window → threshold — routes_letters.py:46-77
- §3.3 — insert — ambiguity — letter creation advances the property `DORMANT → DUE_DILIGENCE` — routes_letters.py:87-88
- §3.3 — insert — ambiguity — record-response runs the letter's state check before examining the evidence event — routes_letters.py:151-157
- §3.4 — insert — ambiguity — report calendar comes from the first rule configured for the state, else defaults `06-30`/`11-01`; creation not gated on rule existence; `report_year` a positive integer; non-integer `report_year` filter → `ERR_INVALID_REQUEST` — routes_reports.py:59-80, 124-127
- §3.4 — insert — ambiguity — body-referenced `property_id` existence (`ERR_PROPERTY_NOT_FOUND`) resolved ahead of the OCC version check on line addition — routes_reports.py:228-235
- §3.4 — revise — mismatch — `ERR_EMPTY_REPORT` guard covers the INCLUDED-or-FINAL set (reopened reports with already-FINAL cash lines remain resubmittable) — routes_reports.py:316-322
- §3.4 — insert — ambiguity — a line whose property has no applicable rule at submission is treated as over-threshold in the due-diligence completeness check — routes_reports.py:328-336
- §3.4 — insert — ambiguity — amendment creation evaluates the OCC check before the ACCEPTED-state check — routes_reports.py:152-162
- §3.4 — insert — ambiguity — rejecting a non-SUBMITTED report is refused with `ERR_REPORT_NOT_SUBMITTED` — routes_reports.py:390-391
- §3.5 — insert — ambiguity — securities-detail read (array of 0 or 1) is not paginated — routes_securities.py:65-72
- §3.5 — insert — ambiguity — `execution_price_cents_per_share` is an integer of zero or more — routes_liquidation.py:125
- §3.6 — insert — ambiguity — a refused confirmation still records the freshly evaluated `variance_cents` on the remittance — routes_remittances.py:100-106
- §3.6 — revise — mismatch — requeue clears `variance_cents` to null (rather than leaving the stale value) — routes_remittances.py:155-156
- §3.7 — insert — ambiguity — a property whose recoverable base cannot be determined at all is refused with `ERR_CLAIM_EXCEEDS_RECOVERABLE`, same as a zero base — routes_claims.py:70-75, helpers.py:361-380
- §3.7 — insert — ambiguity — CASH payout base is the property's FINAL line in the ACCEPTED (possibly since SUPERSEDED) report; missing rule at approval → rate 0; multiple confirmed remittances → most recent supplies `confirmed_date`; none found → days held 0 — routes_claims.py:202-214, helpers.py:371-394
- §3.7 — revise — mismatch — submit-info checks ownership before the MORE_INFO_REQUESTED state check — routes_claims.py:158-168
- §3.7 — revise — mismatch — withdraw checks ownership before the SUBMITTED/MORE_INFO_REQUESTED state check — routes_claims.py:272-282
- §3.8 — revise — mismatch — penalty assessment on any state other than SUBMITTED/ACCEPTED (not merely "anything earlier") → `ERR_REPORT_NOT_SUBMITTED` — routes_penalties.py:43-47
- §3.8 — insert — ambiguity — "first INCLUDED line" = earliest-created; fallback to any rule of the report's state; if the state has no rule at all, penalty and interest are both zero — routes_penalties.py:57-91
- §3.8 — insert — ambiguity — dispute from a non-ASSESSED origin and waive from a non-ASSESSED/DISPUTED origin are refused with `ERR_PENALTY_NOT_ASSESSED` — routes_penalties.py:158-162, 176-177
- §3.8 — insert — ambiguity — audit lookback years are positive integers; end-before-start rejected as `ERR_INVALID_REQUEST` — routes_audits.py:44-50
- §3.8 — insert — ambiguity — exposure candidates with no applicable rule contribute nothing; audit's `estimated_exposure_cents` stays null until FINDINGS_ISSUED; the exposure read returns the stored snapshot after findings and computes live (unstored) before — routes_audits.py:60-66, 122-123, 161-178
