# Worklog — task_1307_securities_filings_section_16_reporting

## Step 1: Create Task Directory — 2026-08-12T19:24:00.000Z

RESUME RUN: task directory `tasks/task_1307_securities_filings_section_16_reporting/` and `workspace/` already exist (empty). Treated as DONE per resume instructions; no index scan performed.

## Step 2: Generate Scaffold — 2026-08-12T20:23:00.000Z

All checks pass. The scaffold for task_1307 is complete and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1307_securities_filings_section_16_reporting/`):

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys). Compliance/audit primary archetype with event-sourcing secondary; flat topology; cyclic state machines; segregation-of-duties role model. 10 entities (Issuer, ReportingPerson, SecurityTransaction, SecuritiesFiling with self-referential `amends_filing_id`, TradingPlan10b5_1, BlackoutWindow, BeneficialHolder, PositionChange as immutable event log, AnnualSweep, FilingAgentAuthorization), 46 endpoints including the `/_clock/set_current_utc` test-driving endpoint with the mandatory `2026-08-01T00:00:00Z` default, 7 state machines (4 non-linear: filing rejection loop, plan suspend/reinstate, person exit/reinstate, holder filed/amendment-required), 8 calculations, 10-priority validation table, 28 error codes, 5 roles (ReportingInsider is `entity_backed:ReportingPerson`), and 2 OCC concurrency rules (`PUT /issuers/{id}`, `POST /filings/{id}/amendments` — both pass the serial-observability filter).

- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — exactly 2 instances per rule (18 total). Highlights: short-swing MAX_RECOVERY vs FIFO divergence (1000.00 vs 700.00) vs basic/fully-diluted ownership (5.00 vs 7.32); cooling-off nested min/max with the 120-day cap binding (2026-12-01) vs per-pair-then-sum rounding (0.02 vs forbidden 0.01); depth-3 late-acceptance cascade (is_late → late_filing_count → delinquent_flag at threshold 2) vs depth-2 confirm cascade; state-vs-temporal and safety-vs-constraint priority pairs; 5.00%-exactly vs deadline-date-exactly boundaries; closed-interval blackout overlap vs half-open plan-window overlap; obligation-count and cooling-off-date conservation invariants.

- `SCAFFOLD_CORNER_DESIGN.yaml` — 41 active instances across all nine claim-extraction sections plus 6 `excluded_because` stubs citing §1.8 instances; covers defaults, immutability, pagination envelope, terminal lockdowns, holiday-aware deadline (2026-08-06 → 2026-08-11), out-of-order balance recompute (100/150), the exactly-six-months short-swing exclusion, OCC 412s on both guarded endpoints, EDGAR CCC rotation, sweep-generated Form 5 (deadline 2027-02-14), SOD four-eyes confirm, and all five roles' denials. All 28 error codes are triggerable by at least one instance or §1.8 stub target.

**Verification**: `scaffold_lint.py` verdict block (verbatim):

```
Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     41
  Calls scanned (§1.8+§1.9):  468

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional audits: no forbidden concurrency vocabulary; 65 unique instance names across both files; every error referenced by a validation/transition; all fixture arithmetic (deadlines, cooling-off dates, short-swing profits, percentages) was pre-computed in Python before being pinned as literals. One fix during linting: the `GET /position-changes` filter param was renamed to `holder_id?` to exactly match the FK field name.

## Step 3: Copy Shared Files — 2026-08-12T20:25:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1307_securities_filings_section_16_reporting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T20:47:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1307_securities_filings_section_16_reporting/workspace/PRD.md`.

**What was generated:** A prose PRD for the Securities Filings & Section 16 Reporting domain — 2-paragraph introduction; §2 with 8 domain-derived subsections (role identities incl. the entity-backed `ReportingInsider`, verbatim §2.2 envelope, pagination, common resource properties with the `PositionChange` exception, the logical clock with its 2026-08-01T00:00:00Z startup default, business-day arithmetic, precision, an explicitly ordered 11-step validation chain, the two OCC rules, segregation of duties, and derived-figure cascades); §3 with 9 workflow subsections (issuer config, designation lifecycle, transaction intake/confirm/void, deadlines & delinquency, the filing pipeline incl. EDGAR disposition and amendments, blackout windows + 10b5-1 plans with the cooling-off formula, beneficial-ownership thresholds, the annual Form 5 sweep, and the two-variant short-swing analysis); §4 minimal 4-column table with all 46 endpoints; §5 two-column catalogue with all 28 error IDs.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 102 required, 102 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority rows: 11 checked, 11 expressed in ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed (preconditions with error ids + side effects), 0 missing
- calculations[]: 8 checked, 8 fully expressed in reconstructible prose (no pseudocode/fuzzy words), 0 missing
- validations[] conditions: 28 error ids all matchable to triggers in §2/§3 prose, 0 missing
- endpoints[].side_effects: 46 checked, 46 expressed, 0 missing
- sibling-branch symmetry: 6 groups (reopen pair, void pair, terminate trio, file-schedule pair, short-swing variants, pct variants), all equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 474
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 matches the fixed block byte-for-byte (confirmed by diff against `section-2.2-response-structure.md`); the file ends at the §5 table with no audit footer; the withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.


## Step 5: Generate Unit Tests — 2026-08-12T21:30:00.000Z

Generation complete. Summary of what was produced for task_1307:

## Stage 1 — `test_helpers/` (9 files)
- `types.py` — 11 status/field enums + 10 entity TypedDicts; `PositionChange` correctly omits `updated_at`/`version` (immutable event per PRD §2.4).
- `api_client.py` — `ApiClient(GenericApiClient)` with 36 endpoint methods covering every PRD §4 operation; `BASE = ""` (scaffold `api_prefix: /`).
- `api_errors.py` — all 28 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity structural assertions; `assert_position_change` asserts absence of `version`/`updated_at`.
- `factories.py`, `constants.py` — payload factories (input fields only) and thresholds (2 business days, 10/45 calendar days, 90/120-day cooling-off, 5.00/1.00 ownership thresholds, delinquency threshold 2).
- `test_users.py` — opaque role constants plus `make_reporting_insider_headers(user_id)` (mandatory per-instance builder; ReportingInsider is entity-backed).
- `fixtures.py` — composite helpers: clock control, issuer/person/plan/holder creation, `create_active_person`, `ingest/confirm/void`, `ready/submit/accept/reject` filing pipeline, `setup_person_with_confirmed_transaction` / `setup_ready_auto_form4` / `setup_accepted_auto_form4`, `setup_adopted_plan` / `setup_active_plan` (insider identity threaded correctly).
- `__init__.py` — barrel export of framework + PRD-specific names.

## Stage 2 — `test_suite/` (conftest + 10 files, 77 tests)
Files: `test_01_issuer_and_auth_envelope` (5), `test_02_reporting_person_designation` (6), `test_03_transaction_confirm_and_void` (12), `test_04_trading_controls_blackout` (4), `test_05_trading_plans` (14), `test_06_filing_pipeline` (14), `test_07_filing_amendments` (4), `test_08_beneficial_ownership` (8), `test_09_short_swing_analysis` (5), `test_10_annual_sweep` (3).

## Audit results
- **Coverage**: all 18 difficulty instances have ≥2 tests (36 total); all 41 non-stub corner instances have ≥1 test (41 total). All 6 `excluded_because` stubs verified to resolve to real difficulty instances and were not translated.
- **Tags**: every one of the 77 docstrings ends with exactly one verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; zero bogus tags.
- **Citations**: every test carries PRD §-cited quotes that pass full-string verbatim matching against `PRD.md` (whitespace-normalized).
- **No** `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

## Adjudication notes (PRD-first filter)
- **`matchable_pair_count` assertions dropped** in both short-swing instances (`short_swing_max_recovery_vs_fifo`, `six_month_window_exactly_excluded`): the two design instances imply mutually inconsistent pair-count semantics (2 under a cartesian reading vs 1 under a matched-pairs reading), so the count fails the two-reader test. The instances are still fully exercised through the uniquely-derivable profit figures (1000.00/700.00; 400.00/400.00), which pin the underlying rules.
- **Absolute version literals relaxed** (`put_issuer_stale_version_returns_412`): PRD pins "increments by one" but never the initial version value, so the test asserts `version == captured + 1` instead of the YAML's hard-coded `2`. The core OCC claim (stale → `ERR_STALE_VERSION`/412) is asserted verbatim.
- All computed dates cross-checked by hand (e.g., cooling-off cap binding at 2026-12-01; 2026-08-06 + 2 business days = 2026-08-10; holiday-skipped deadline 2026-08-11; Form 5 deadline 2027-02-14; FY window 2026-01-01..2026-12-31).

## Step 6: Generate Implementation — 2026-08-12T21:30:00.000Z

Implementation complete. Here is the summary:

## What was built

A complete Python + Flask REST API implementation for the Securities Filings & Section 16 Reporting benchmark task, located in:

**`/home/ubuntu/github/CodingPRD/tasks/task_1307_securities_filings_section_16_reporting/workspace/implementation/`**

### Files

| File | Purpose |
|------|---------|
| `start.sh` | Foreground launcher; guards `pip install` with `import flask` check; `exec python3 app.py` |
| `requirements.txt` | `flask>=2.3.0` |
| `app.py` | Entry point, blueprint registration, error handlers |
| `db.py` | In-memory store (empty on every boot, no seeding) |
| `errors.py` | All error IDs and `ApiError` exception class |
| `response.py` | Success/error envelope builders per PRD §2.2 |
| `middleware.py` | `X-User-ID` / `X-User-Role` extraction and role validation |
| `utils.py` | Logical clock, business-day arithmetic, pagination, serialization |
| `routes/clock.py` | `POST /_clock/set_current_utc` |
| `routes/issuers.py` | Issuer CRUD + OCC-guarded PUT |
| `routes/blackout_windows.py` | Blackout window CRUD + overlap check |
| `routes/reporting_persons.py` | Person CRUD + DESIGNATE/EXIT/REINSTATE + short-swing analysis |
| `routes/transactions.py` | Transaction ingest/confirm/void with full cascade |
| `routes/filings.py` | Filing pipeline: create, ready, reopen, discard, submit, record-edgar-result, amendments |
| `routes/trading_plans.py` | Plan CRUD + full lifecycle (SUBMIT_ADOPTION through TERMINATE) |
| `routes/beneficial_holders.py` | Holder CRUD + position changes + file-schedule |
| `routes/annual_sweeps.py` | Sweep CRUD + run |
| `routes/filing_agent_authorizations.py` | Authorization CRUD + revoke |
| `services/calculations.py` | Business logic: filing deadlines, cooling-off, balance chain, short-swing (both variants), annual sweep, open obligations, holder thresholds |

### Key behaviors verified by smoke tests

- **Logical clock**: defaults to `2026-08-01T00:00:00Z`, settable via `POST /_clock/set_current_utc`
- **Validation ordering**: auth (400) -> role (403) -> not found (404) -> body shape (400) -> OCC (412) -> state (409) -> cross-entity (409) -> compliance guards (403/422) -> temporal (422) -> business constraints (409) -> referential (400/422)
- **Transaction confirm cascade**: direction computed, balance chain recomputed, auto Form 4 created for non-G codes, `open_obligation_count` incremented
- **Void compensation**: linked DRAFT/READY filing discarded, transactions detached, balance chain recomputed
- **Filing pipeline**: DRAFT -> READY -> SUBMITTED -> ACCEPTED/REJECTED, with SOD and EDGAR CCC checks
- **Late filing & delinquency**: `is_late` computed once at acceptance, `late_filing_count` increments, `delinquent_flag` latches at 2
- **Amendments**: OCC-guarded creation against ACCEPTED filing, supersedes original on acceptance
- **10b5-1 plans**: full lifecycle including cooling-off computation (90-day base, officer/director extension with 120-day cap), suspend/reinstate preserving `cooling_off_end_date`
- **Beneficial holders**: append-only position changes, threshold transitions (5% filing, 1% amendment drift), issuer `shares_outstanding` update recomputes all holders
- **Annual sweep**: in-scope person filtering, per-person late/unreported/delinquent counts, auto Form 5 creation
- **Short-swing analysis**: both MAX_RECOVERY and FIFO_CHRONOLOGICAL variants with per-pair rounding then summation
- **Pagination**: `limit`/`offset`/`total_count`/`has_more` in `meta`, default 10, max 100

## Step 7: Run Tests and Iterate — 2026-08-12T21:55:00.000Z

All 8 rounds pass cleanly: 77/77 in every round, zero failures, zero errors. Exiting with the summary.

## Summary

- **Iterations run:** 3 eight-round parallel sweeps (initial diagnosis → after test fix → after implementation fix, final clean sweep).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1307_securities_filings_section_16_reporting/test_suite/test_09_short_swing_analysis.py` — `TestSixMonthWindowBoundary.test_six_month_window_exactly_excluded`: added `set_clock("2026-08-06T00:00:00Z")` before confirming the transactions. The test confirmed transactions dated 2026-08-04/2026-08-05 while the logical clock sat at its boot default of 2026-08-01 (PRD §2.5), so the PRD-faithful future-date guard (`ERR_FUTURE_TRANSACTION_DATE`, PRD §3.3) correctly rejected the setup — a test bug, fixed in the test, not by weakening the implementation check.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1307_securities_filings_section_16_reporting/workspace/implementation/services/calculations.py` — `short_swing_analysis.is_matchable`: changed the six-month window check from OR to AND (`s_date < p_date+6mo AND p_date < s_date+6mo`). With OR, every purchase-earlier-than-sale pair was trivially matchable, so an exactly-six-months-apart pair (2026-02-05 / 2026-08-05) was incorrectly matched — violating PRD §3.9's verbatim rule "A purchase and a sale exactly six calendar months apart are not matchable." (profit 800.00 → 400.00 as required).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1307_securities_filings_section_16_reporting/workspace/implementation/app.py` — wrapped `app.run` in a bounded bind-retry loop (60 × 0.5s on `OSError`). Under the 8-way concurrent sweep the runner kill -9s the previous server and immediately respawns; under load (host load avg ~46) the old listener occasionally hadn't released the port, the new server died on EADDRINUSE, and the runner's 15s readiness poll expired, producing sporadic "could not be restarted" setup errors in 4 of 8 rounds. Bootstrap-only change, no API behavior affected.

Final state: 8/8 rounds at 77/77 passed, 0 failed, 0 errors.

## Step 8: Finalize PRD — 2026-08-12T22:10:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1307_securities_filings_section_16_reporting/workspace/PRD_FINALIZED.md` is written with exactly one one-word revision.

## Summary

**Line counts:** PRD.md 319 lines, PRD_FINALIZED.md 319 lines — 0% delta (single-word in-place revision on line 229).

**Changes:**
- §3.9 — revise — changed the six-month matchability elaboration from "or" to "and" ("the sale's date falls before the purchase's date plus six calendar months, **and** the purchase's date falls before the sale's date plus six calendar months"). The PRD's "or" admitted an OR-reading under which an exactly-six-months-apart pair (e.g., 2026-02-05 / 2026-08-05) is matchable via the second disjunct, contradicting the PRD's own next sentence "A purchase and a sale exactly six calendar months apart are not matchable." The implementation resolves this with a conjunction of both strict inequalities — `implementation/services/calculations.py:159-162` (`is_matchable`).

**Step_7_diff items not requiring edits:**
- *Test fix (`test_09` `set_clock` before confirm):* pure test bug. PRD already pins the boot-default clock (§2.5: "On server startup the clock reads exactly 2026-08-01T00:00:00Z") and the future-date guard (§3.3, §2.8 item 9). Implementation is PRD-faithful: `implementation/db.py:24` (clock default) and `implementation/routes/transactions.py:138-139` (`ERR_FUTURE_TRANSACTION_DATE` at confirm). No PRD silence.
- *Impl fix (`app.py` bind-retry loop):* bootstrap-only port-rebind resilience under the test runner; zero API-visible behavior. The PRD scopes API behavior only, so there is nothing to pin — `implementation/app.py:54-67`.

**Per-edit pre-edit search log:**
- **Edit 1 (§3.9 "or"→"and"):**
  - (a) Subject: the six-calendar-month matchability window predicate for short-swing purchase/sale pairs.
  - (b) Impl paths enumerated and read/grepped: `implementation/services/calculations.py:152-162` (the `is_matchable` definition — the Step 7 site); `calculations.py:176` (MAX_RECOVERY candidate filter) and `calculations.py:214` (FIFO candidate filter) — both variants share the single predicate, no per-variant divergence; `implementation/utils.py:53-64` (`add_calendar_months` with end-of-month clamp — grep confirmed `is_matchable` is its sole caller, and the clamp is already pinned verbatim in PRD §3.9); `implementation/routes/reporting_persons.py:151-154` (endpoint is a thin pass-through to `short_swing_analysis`, no independent window logic). Repo-wide grep for `add_calendar_months|is_matchable|six|month` across `implementation/` found no other matchability/window code paths.
  - (c) Wording adjustment: kept the surrounding clause "in either order" — with the conjunction of both directional strict-inequalities the predicate is symmetric, which is exactly what "in either order" conveys, and it stays true for both the MR and FIFO paths. Strict less-than on both conjuncts preserves the following sentence ("exactly six calendar months apart are not matchable") in both date orders. No widening or re-scoping was needed; no other enumerated path is mis-described by the one-word change.

## Step 9: Complete PRD — 2026-08-12T22:35:00.000Z

All edits verified via diff. The file is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1307_securities_filings_section_16_reporting/workspace/PRD_COMPLETED.md`.

## Summary

**Source**: `PRD_FINALIZED.md` (319 lines / 50,802 chars) → `PRD_COMPLETED.md` (319 lines / 54,248 chars; char-delta **+3,427**). 15 lines edited, carrying 20 logical changes. No sections added or removed.

**Counts**: 16 ambiguity-pins, 4 mismatch-revisions.

### Changes

- **§2.1** — insert — ambiguity — non-empty but unrecognized `X-User-Role` value is rejected with `ERR_FORBIDDEN_ROLE` (403), not the header error — `implementation/middleware.py:29-30`
- **§2.3** — revise — ambiguity — out-of-range/unparseable pagination values are clamped/defaulted, never rejected (non-integer → default; limit<1→1; limit>100→100; offset<0→0) — `implementation/utils.py:165-180`
- **§2.3** — insert — ambiguity — `created_at` ties (common under the frozen logical clock) preserve creation order — `implementation/routes/issuers.py:63` (stable sort pattern in all list endpoints)
- **§2.3** — revise — ambiguity — `total_count` = post-filter count; `has_more` true iff `offset` + page size < `total_count` — `implementation/response.py:38`
- **§2.3** — revise — ambiguity — replaced the dangling "as itemized per endpoint in §4" with the exact per-endpoint filter sets (issuers: none; transactions: 5 filters; filings: 5; etc.) — `implementation/routes/*.py` list handlers
- **§2.9** — insert — ambiguity — on issuer PUT, `expected_issuer_version` presence is enforced first (`ERR_INVALID_REQUEST`), then version equality, then validation of the updated field values — `implementation/routes/issuers.py:81-104`
- **§2.11** — revise — ambiguity — `open_obligation_count` is a full recount on every filing create/status change: rejection also lowers it, reopen-from-REJECTED raises it, and every recomputation bumps the person's `version`/`updated_at` even when the count is unchanged — `implementation/services/calculations.py:335-345`
- **§3.3** — revise — ambiguity — `source` is stored verbatim from the request, defaults to `MANUAL`, with **no enum validation** — `implementation/routes/transactions.py:78`
- **§3.3** — insert — ambiguity — `direction` is null at intake and derived only at confirmation — `implementation/routes/transactions.py:79,147`
- **§3.3** — insert — mismatch — balance-chain cascade rewrites touch only `shares_owned_after` and do not refresh `updated_at`/`version` on other transactions in the chain (carves out §2.4's blanket rule) — `implementation/services/calculations.py:73-84`
- **§3.3** — revise — mismatch — void `reason` is accepted but not persisted anywhere (PRD said "recording a `reason`"; impl stores nothing) — `implementation/routes/transactions.py:179-208`
- **§3.3** — revise — mismatch — void-time detachment clears `filing_id` without bumping detached transactions' `updated_at`/`version` — `implementation/routes/transactions.py:199-201`
- **§3.5** — insert — ambiguity — manual FORM_4 with omitted/empty `transaction_ids` yields `ERR_INVALID_REQUEST` (not `ERR_TRANSACTION_NOT_ATTACHABLE`, which is reserved for named-but-unattachable transactions) — `implementation/routes/filings.py:70-82`
- **§3.6** — insert — ambiguity — plan dates must be well-formed and `expiration_date` strictly later than `first_trade_date`, else `ERR_INVALID_REQUEST` — `implementation/routes/trading_plans.py:45-52`
- **§3.6** — revise — ambiguity — `ACTIVATE` is a `ComplianceOfficer`-only action — `implementation/routes/trading_plans.py:141-142`
- **§3.6** — insert — ambiguity — `SUSPEND` and plan-`REINSTATE` are both `ComplianceOfficer` actions — `implementation/routes/trading_plans.py:149-161`
- **§3.7** — insert — ambiguity — `fully_diluted_pct` is 0 when its denominator (`shares_outstanding` + derivative shares) is not positive — `implementation/services/calculations.py:118-124`
- **§3.8** — insert — mismatch — sweep-time attachment of gift transactions sets only `filing_id`, leaving their `updated_at`/`version` untouched — `implementation/services/calculations.py:318-320`
- **§3.9** — revise — ambiguity — `as_of_date` is the logical clock date; `pairs` enumerates the maximum-recovery pairings in emission order with `matchable_pair_count` as its length; pair fields are `purchase_transaction_id`, `sale_transaction_id`, `matched_shares`, `profit` — `implementation/services/calculations.py:240-248`
- **§3.9** — insert — ambiguity — in both variants a partially-matched sale continues to the next eligible purchase (next-lowest-priced / next-earliest) until exhausted, each allocation becoming its own pair — `implementation/services/calculations.py:183-193,220-230`

Notable areas verified as already uniquely pinned (no change): validation-order §2.8 vs impl check ordering on confirm/submit/record-edgar-result/amendments; all error-id→HTTP-status mappings; cooling-off formula incl. officer/director extension and 120-day cap; deadline formulas; state machines; SoD rules; sweep scope/row formulas; the FINALIZED "and" fix in the six-month matchability rule (matches impl's conjunctive check).
