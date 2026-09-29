# Worklog — task_2390_research_billing_coverage_analysis_study

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2390_research_billing_coverage_analysis_study/` and `workspace/` (directory name pre-allocated by the invoker; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T07:22:00.000Z

Task 2390 scaffold is complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2390_research_billing_coverage_analysis_study/`)
- `SCAFFOLD.yaml` (2567 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1896 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3632 lines) — single key `scaffold_corner_design`

**SCAFFOLD.yaml contents**
- Domain `research-billing` (global `api_prefix: /research-billing`), logical clock default `2026-08-01T00:00:00Z`
- 12 entities: Study, CoverageAnalysis, CoverageItem, StudyCalendar, CalendarVisit, VisitChargeRoute, StudySubject, SubjectVisit, Charge, SponsorInvoice, AuditFinding, Amendment
- 9 state machines (Study runs two independent dimensions: lifecycle DRAFT→…→CLOSED_TO_ACCRUAL with a cycle back via amendment, and budget NOT_BUILT→BUILT→EXECUTED→SUPERSEDED; Charge likewise splits routing vs billing)
- 3 OCC concurrency rules (`analysis-create-stale-study`, `budget-build-stale-study` → ERR_STALE_STUDY_VERSION 412; `item-add-stale-analysis` → ERR_STALE_COVERAGE_ANALYSIS_VERSION 412)
- 10 calculations (indirect-rate surcharge-before-cap with federal/industry caps and a 500000 tier; dual-variant budget totals and dual-variant routing expectation; invoice waterfall line selection with STOP-not-skip; per-line-rounded indirect; tiered volume credit on gross; posture fixed-point propagation; aging buckets; ledger rollup invariants P and S)
- 37 ordered validations (priorities 1–44), 51 endpoints, 63 error codes, 5 roles under a segregation-of-duties model (analysis approver ≠ preparer, budget executor ≠ builder, finding responder ≠ opener)

**§1.8 difficulty design** — all 9 rules, 23 instances (2–3 per rule), each with exact pre-computed arithmetic.

**§1.9 corner design** — 96 instances over the 9 fixed taxonomy sections: 62 full test recipes + 34 legitimate `excluded_because` stubs (every citation resolves to a real §1.8 instance name). Section spread: entities 12, state_machines 15, calculations 13, validations 9, endpoints 6, errors 31, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1. All 63 error codes are now referenced by at least one instance (I added 13 error instances this pass to close a 20-code coverage gap).

**One SCAFFOLD change made to keep a code reachable**: BG-1's precondition now allows `budget_status == EXECUTED` (mid-study rebuild drops the budget back to BUILT and clears the executor), which makes `ERR_BUDGET_NOT_EXECUTED` reachable on consent while the study stays OPEN_TO_ACCRUAL.

**Lint**: `python3 /home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py <task-dir>` → `VERDICT: clean lint` (51 endpoints, 12 entities, 23 §1.8 instances, 62 §1.9 instances, 863 calls scanned). No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-02T07:23:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T07:38:00.000Z

PRD generated and audited.

**Output:** `workspace/PRD.md` — **428 lines**

**Structure** (ends at §5 as required):
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 11 subsections: 2.1 Billing Office Roles and Request Authentication, 2.2 API Response Structure (pasted byte-for-byte), 2.3 Pagination, 2.4 Record Identity/Timestamps/Logical Clock, 2.5 Segregation of Duties, 2.6 Version Guards, 2.7 Money/Rounding/Two Pinned Indirect Orders, 2.8 Study Ledger & Conservation Invariants, 2.9 Billing Hold Posture, 2.10 Cascade Discipline, 2.11 Validation Order
- §3 Business Logic & Workflows — 9 domain subsections
- §4 Endpoint Definitions — 4-column table, 51 rows
- §5 Error Code Catalogue — 2-column table, 63 rows

**Hard Contract 1 — Field-Name Coverage: PASS.** 136/136 entity fields, 62/62 request/query/path/output identifiers, 63/63 error ids present verbatim in backticks. All enum values and state names verified present.

**Hard Contract 2 — Rule Coverage: PASS.** All 9 state machines / 35 transitions, 10 calculations (with traps stated: sum-then-round vs round-per-line-then-sum; industry surcharge before the 32.0 cap; volume-credit tier keyed on pre-credit gross; line-selection stop-never-skip with strictly-greater 2,000,000-cent comparison; inclusive aging bucket bounds; closed-interval visit-window overlap), 3 concurrency rules + sponsor-invoice `expected_study_version`, 37 validations with paired error ids and ordered precedence in §2.11, all six high-risk categories.

**Hard Contract 3 — §3 Path Purity: PASS.** All 802 backtick spans in §3 scanned: zero paths, zero bare HTTP methods.

§4's 51 rows match the scaffold's 51 endpoints exactly. Design yamls never opened; no sibling task read.

## Step 5: Generate unit tests — 2026-09-02T09:10:00.000Z

Task complete. Final state of the generated suite for task 2390:

## Files

**`test_helpers/`** (Stage 1, 9 files): `__init__.py` (barrel), `api_client.py` (`PREFIX="/research-billing"`), `api_errors.py`, `types.py`, `test_users.py` (two distinct identifiers per role for the three SoD rules), `constants.py`, `factories.py`, `assertions.py`, `fixtures.py` (tier-0 verb helpers plus composites up to `setup_submitted_invoice` / `setup_refundable_finding` / `setup_rebuild_blocked_study`).

**`test_suite/`** — 13 test modules + `conftest.py`, **111 collected tests / 109 test functions** (two `parametrize` cases):
- Queue A (depth): `test_01`–`test_06` — 47 tests over **23/23** non-stub difficulty instances (every instance >=2 tests).
- Queue B (breadth): `test_10`–`test_16` — 62 tests over **62/62** non-stub corner instances (every instance >=1 test). New this session: `test_15_state_and_workflow_errors.py` (11 `Corner/errors`) and `test_16_roles_and_concurrency.py` (3 `Corner/rbac` + 3 `Corner/cross_cutting_complexity_layers`).

## Audit results (all clean)

- Every test docstring carries exactly **one** `Design:` line; no tag points at a stub or a non-existent instance; the 34 `excluded_because:` stubs were never translated.
- Every test carries a PRD citation that is verbatim-greppable in `workspace/PRD.md` (111 citations checked after normalizing whitespace) and >=8 words. Five citations were repaired during the audit because a clause had been terminated with an invented period (`test_12`/`test_13`/`test_14`/`test_15` x2) and one 7-word non-rule-bearing quote in `test_02` was replaced with the volume-credit tier sentence.
- No `skip`/`xfail`/`TODO`, no `validate_error_is_one_of` (all precedence pairs assert the exact code per §2.11), no reference to the scaffold anywhere in generated code, pyflakes clean.

## Instances skipped

**None.** All 23 queue-A and all 62 non-stub queue-B instances were translated. What was dropped is individual PRD-silent *assertions*, not instances: the invoice's initial `amount_paid_cents` ("at their initial values"), the analysis' stored return-reason field name, the exact calendar `version` delta on route creation (only `>` asserted), fresh-study budget-figure nulls (`budget_basis`, `effective_indirect_rate_pct`) — a refused build cannot be distinguished from an undeclared initial value — fresh-charge `aging_days`/`aging_bucket`/`hold_applied_at`, the `?classification=` items filter, and any list-order assertion where rows share one logical instant.

Two recipe deviations worth noting: the `amendment_cannot_be_implemented_before_its_effective_date` recipe was internally inconsistent (it left the study at `DRAFT`, where implementation can never succeed), so that test isolates the effective date by starting from an approved analysis; and the accrual refusal for a DRAFT-only calendar asserts the generic `ERR_INVALID_STATE_TRANSITION`, since §2.11 lists no domain-specific code for that endpoint.

## Step 6: Generate implementation — 2026-09-02T09:10:00.000Z

Implementation complete and verified.

## Files created
`workspace/implementation/` — 21 files:

- `start.sh` — `set -euo pipefail`, `cd` to its own dir, guarded `pip install` (only when `import flask` fails), then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000). Measured cold boot to first 200: ~7s on this loaded host.
- `requirements.txt`, `app.py` (app factory + ApiError/404/405/400/HTTPException/Exception handlers)
- Core modules: `store.py` (12 empty dicts, logical clock pinned to `2026-08-01T00:00:00.000Z`, seq/id/version helpers), `envelope.py`, `auth.py`, `validation.py`, `serializers.py`, `lookup.py`, `errors.py` (all 66 catalog ids + status map), `derive.py` (all read-derived projections and money math)
- `routes/`: `studies, coverage, calendars, subjects, charges, invoices, audit, amendments, ops` (+ `__init__.py`)

## Endpoints
**51**, matching the PRD §4 table exactly — a programmatic diff of the PRD table against the registered Flask rules reports `PRD-only: []`, `Impl-only: []`, `matched: 51 of 51`.

## Notable design decisions
- **Derived on read, never stored**: study billing posture, all 8 ledger positions, `improper_flag`/`expected_routing_target`, the analysis' five counters, calendar counters, subject/visit charge counts. Invoice money fields are *stored* because a dispute zeroes them and re-submission recomputes selection.
- **Two coverage views kept strictly separate**: the *operational* view (candidates APPROVED+SUPERSEDED, `approved_at` <= service-date `23:59:59.999Z`) decides review agreement; the *audit* view (APPROVED only) is what `expected_routing_target` exposes, so a later revision retroactively raises `improper_flag` on already-billed charges without changing history.
- **Two pinned rounding orders**: budget = sum-then-round; invoice indirect = round-per-line-then-sum. All money in `Decimal` with `ROUND_HALF_UP`, no floats.
- **Version-bump policy** made explicit and uniform: every cascade that mutates a row calls `store.touch` (per PRD §2.10), including aged charges and auto-missed visits during `_ops/aging-run`.
- **Undeclared failure modes** fall back to `ERR_INVALID_STATE_TRANSITION` (409) — e.g. submitting an empty grid, re-submitting a `RETURNED` analysis without an intervening edit, accrual-open preconditions, consent without exactly one PUBLISHED calendar.
- PRD §2.11's fixed 37-step validation order is implemented as the literal check sequence in each handler, overriding the scaffold's per-rule priorities where they differ.

## Verification
Two throwaway smoke suites against fresh boots, ~110 assertions total, both **0 failures**: suite 1 covers the happy path end-to-end plus RBAC/pagination/404s; suite 2 covers the divergence cases (federal 26% cap, investigator-initiated 0%, industry small-study +3 surcharge, round-per-line-then-sum, volume credit at the 1,000,000 threshold, invoice STOP at exactly 2,000,000 gross, supersession improper-flag flip, operational-vs-current view disagreement + override, daily visit capacity, close-to-accrual cascade, bounded return loop, QCT downgrade block). Fresh boot confirmed to return empty collections for every entity; no stray test servers left listening.

## Step 7: Run tests and iterate — 2026-09-02T14:05:00.000Z

Clean sweep achieved.

**Iterations run: 2** (two full 8-round parallel sweeps, both under `setsid nohup`).

**Final result:** all 8 rounds report `passed == total == 111`, `failed 0`, `errors 0`, equal totals across rounds, and `sweep.log` contains zero `FAILED`/`ERROR` lines.
- Results: `workspace/implementation/results.{1..8}.json`
- Log: `workspace/sweep.log`

**Tests deleted: none.**
**Fixes applied to `test_helpers/`: none.**
**Fixes applied to `test_suite/`: none.**
**Fixes applied to `implementation/`: none.**

### Why no changes were warranted

Sweep 1 was 7/8 rounds green at 111/111. The single failure was `test_13_endpoint_round_trips.py::TestAccrualNeedsAPublishedCalendar::test_05_publishing_the_only_calendar_is_what_opens_accrual`, failing with `requests.exceptions.ConnectionError: RemoteDisconnected` partway through its fixture chain (`setup_study_with_executed_budget -> ... -> add_item -> read_analysis`).

Root cause was established as environmental, not an artifact defect:

1. The failing round's server log (`/tmp/prd_bench_server_58059.log`, port resolved from the round's `release_port` line in `sweep.log`) shows the request sequence stopping exactly where the traceback stops — `POST /coverage-analyses` 201, then nothing — followed by the literal line **`Terminated`**. The runner only ever uses `kill -9` for per-test teardown, which prints `Killed`; `Terminated` means an external SIGTERM.
2. Cross-correlating the `Terminated` timestamps across all eight of this task's port logs showed them clustered at identical wall-clock instants (13:33:51/52, 13:34:13-15, 13:34:25) — the documented "same wall-clock instant" reaping tell.
3. Scanning every other pipeline's `/tmp/prd_bench_server_*.log` on this host showed **83 unrelated servers dying at those same instants** (35 at 13:33, 83 at 13:34, 41 at 13:38). This is a host-wide broadcast SIGTERM from some other process on this shared machine (it matches every `python3 app.py`), hitting dozens of concurrently-running tasks. It is not the runner, not this task's `start.sh`, and not reachable from any PRD rule.
4. There was no server-side traceback, no `ERR_INTERNAL`, and no `could not be restarted` warning anywhere in `sweep.log`; the endpoint in question has no timing logic.

Per the load-contention guidance, the sweep was re-run rather than "fixed", and sweep 2 came back fully green on all 8 rounds. Considered and deliberately rejected: adding a `SIGTERM` ignore to `implementation/app.py` to immunise against the external reaper — it would be environment-hardening unrelated to any PRD sentence, and sweep 2 proved it unnecessary.

Note for any future re-run of this task on this host: the broadcast SIGTERM recurs roughly every ~20 minutes in bursts, so an isolated `RemoteDisconnected`/`ConnectionError` in one round should be re-swept before it is diagnosed — the signature to check is a `Terminated` (not `Killed`) line in `/tmp/prd_bench_server_<port>.log` at an instant shared with other tasks' logs.

### Orchestrator verification

Independently re-read all 8 results files: every round `passed=111 total=111 failed=0 errors=0`. Step 7 complete.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T14:08:00.000Z

Skipped per the skill's skip condition. Step 7 produced **0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — the second sweep was a re-run to disprove a host-wide external SIGTERM, not a fix iteration, so no artifact changed between sweep 1 and sweep 2.

Consequence: `<step_7_diff>` is empty. Step 8's hard scope is "every PRD edit must trace to a specific fix listed in `<step_7_diff>`", so with an empty diff there is no in-scope edit Step 8 could make. Running it anyway would force it into a globally-scoped PRD-vs-implementation scan — which is exactly Step 9's job, under instructions written for it. `workspace/PRD_FINALIZED.md` is therefore intentionally absent and Step 9 will start from `workspace/PRD.md`.

Judgement call recorded for the audit trail: this task directory was resumed, and filesystem mtimes show a *prior, unlogged* run touched `implementation/derive.py` (09:44) and other impl files after generation (07:43-07:56), i.e. some earlier fix work exists with no worklog entry and no recoverable diff. That is a further reason Step 8 cannot be run meaningfully here — its focus list is unrecoverable — and a further reason Step 9's exhaustive full-implementation scan is the correct instrument: it does not depend on a diff and will surface any PRD silence those unlogged fixes resolved.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T14:12:00.000Z

`PRD_COMPLETED.md` is written. Source was `workspace/PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md`).

### Counts

- **Source** `PRD.md`: 428 lines / 81,451 chars → **`PRD_COMPLETED.md`**: 433 lines / 93,980 chars (**+5 lines, +12,476 chars**)
- **34 edit hunks**: 26 ambiguity-pins, 8 mismatch-revisions. No sections added; one new paragraph (§2.3 filter naming), three new rows appended to the §5 error table, everything else in-paragraph.

### Changes

- §2.2 envelope bullets — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case/digit chars; `api_request_timestamp` reads the **logical** clock, not wall time — `envelope.py:14`, `store.py:89`
- §2.2 error bullets — insert — ambiguity — unmatched path → `ERR_NOT_FOUND` 404, wrong method → `ERR_METHOD_NOT_ALLOWED` 405, unexpected failure → `ERR_INTERNAL` 500; trailing slashes ignored — `app.py:32,42,47,64`
- §2.3 ¶1 — insert — ambiguity — non-integer/empty `limit`/`offset` → `ERR_INVALID_PAGINATION`, whitespace tolerated; `total_count` = post-filter/pre-window count; `has_more` = `offset + len(rows) < total_count` — `envelope.py:39,56,86`
- §2.3 — insert (new ¶) — ambiguity — filter params named for their field, exact string equality, empty/unknown params ignored; names the four off-pattern cases (`status`→`lifecycle_status`, `budget_source_analysis_id`, `classification`, invoice/amendment `status`) — `studies.py:85,276,289`, `coverage.py:87`
- §2.3 ¶2 — insert — ambiguity — equal `created_at` ties broken by creation sequence, never by id — `store.py:119`
- §2.4 — revise — ambiguity — `updated_at` equals `created_at` until first mutation — `store.py:107`
- §2.4 — revise — ambiguity — `to_iso8601` accepted forms (fraction optional, `Z`/offset/naive→UTC), backwards moves allowed, store starts empty; `current_utc` shape — `validation.py:150`, `ops.py:65`, `store.py:43`
- §2.6 — revise — **mismatch** — a revision does **not** push `COVERAGE_APPROVED` back to `COVERAGE_PENDING`; only the first analysis on a `DRAFT` study moves the lifecycle/version — `coverage.py:56`
- §2.7 — revise — **mismatch** — `effective_indirect_rate_pct` is not "one decimal place"; it is exact and may carry two decimals; both rate fields are JSON numbers, null before a build — `derive.py:357`, `serializers.py:36`
- §2.11 #3 — insert — ambiguity — absent/unparseable body = empty object; non-object body rejected; required strings non-empty; integers reject bools/fractions; explicit null = absent; undeclared fields ignored — `validation.py:19,28,75`
- §2.11 #7 — revise — ambiguity — complete body-FK resolution list with per-endpoint order and codes; FKs are existence-only, not ownership-checked — `coverage.py:31`, `calendars.py:123`, `subjects.py:104`, `charges.py:31`, `audit.py:31`, `ops.py:19`
- §3.1 — insert — ambiguity — supplied `registry_number` written only on full success; failed gates write nothing — `studies.py:136`
- §3.1 — insert — ambiguity — every successful QCT determination increments the study's `version` — `studies.py:142`
- §3.2 — revise — ambiguity — new analysis' four null stamps; no study mutation when past `DRAFT`; `supersedes_analysis_id` need only exist — `coverage.py:41,56`
- §3.2 — insert — ambiguity — each accepted item increments the owning analysis' `version` — `coverage.py:154`
- §3.4 — insert — **mismatch** — calendar creation does **not** gate the source analysis' status or ownership; only publication requires `APPROVED` — `calendars.py:19`
- §3.4 — insert — ambiguity — `window_start_day` may be negative and is not rejected — `calendars.py:92`
- §3.4 — insert — ambiguity — each accepted visit increments the calendar's `version` — `calendars.py:111`
- §3.4 — insert — **mismatch** — `unrouted_per_patient_item_count` reads zero while the generation has no visits, whatever the source analysis holds — `derive.py:155`
- §3.4 — revise — ambiguity — non-`APPROVED` source analysis at publish → `ERR_INVALID_STATE_TRANSITION`, after the `DRAFT` guard — `calendars.py:181`
- §3.5 — revise — ambiguity — wrong-owner/non-`APPROVED` source at budget build → `ERR_INVALID_STATE_TRANSITION`; `indirect_rate_pct` required — `studies.py:153,162`
- §3.5 — revise — **mismatch** — effective rate is exact/unrounded with one-or-two decimals, not "one decimal place" — `derive.py:357`
- §3.5 — revise — ambiguity — the four accrual-open preconditions all report `ERR_INVALID_STATE_TRANSITION`, in the listed order — `studies.py:211`
- §3.5 — revise — ambiguity — closing accrual from any state but `OPEN_TO_ACCRUAL` → `ERR_INVALID_STATE_TRANSITION` — `studies.py:228`
- §3.6 — revise — ambiguity — "not exactly one `PUBLISHED` calendar" at consent → `ERR_INVALID_STATE_TRANSITION` — `subjects.py:84`
- §3.6 — revise — ambiguity — unconsented subject → `ERR_CALENDAR_VISIT_NOT_ON_CONSENTED_CALENDAR`; pinned-calendar check precedes it; subject `status` not re-examined at scheduling — `subjects.py:107`
- §3.6 — revise — ambiguity — visit-status and subject-status failures at completion are both `ERR_INVALID_STATE_TRANSITION`, visit first — `subjects.py:169,173`
- §3.6 — insert — ambiguity — cascade charge's `charge_code`/`study_id`/`service_date`/`subject_visit_id` sources, plus the universal new-charge defaults (`hold_reason`, `aging_days` 0, `aging_bucket` `CURRENT`, `refunded_amount_cents` 0, five nulls) — `subjects.py:187`, `derive.py:273`
- §3.6 — revise — ambiguity — `subject_visit_id` on an interface post is existence-only; posting bumps no other `version`; linked charge counts in `charge_count` but not `generated_charge_count` — `charges.py:32`, `serializers.py:165`
- §3.7 — insert — ambiguity — both analysis views break a surviving tie by creation sequence and discard null `approved_at` — `derive.py:226`
- §3.7 — insert — ambiguity — empty/absent `override_justification` leaves the stored value untouched — `charges.py:93,109`
- §3.8 — revise — ambiguity — invoice opens with `submitted_at` null and `amount_paid_cents` zero — `invoices.py:56`
- §3.8 — revise — **mismatch** — the selector is **not** re-run on every submission; only a `DISPUTED` re-submit re-selects, a `DRAFT` submit carries the creation-time selection — `invoices.py:79`
- §3.8 — revise — ambiguity — selection tie-break by creation sequence — `derive.py:389`
- §3.8 — insert — ambiguity — a null `effective_indirect_rate_pct` is read as 0 percent rather than refused — `derive.py:44,380`
- §3.8 — revise — **mismatch/ambiguity** — omitted `amount_paid_cents` on `SHORT_PAID` is `ERR_REMITTANCE_AMOUNT_INVALID`; `PAID_IN_FULL` omission records the net; `DISPUTED` ignores the amount — `invoices.py:112,122,131`
- §3.9 — insert — ambiguity — amendment filing gates nothing and does not move the study's `version` — `amendments.py:31`
- §3.9 — revise — ambiguity — non-`COVERAGE_APPROVED`/`OPEN_TO_ACCRUAL` study at implement → `ERR_INVALID_STATE_TRANSITION` — `amendments.py:53`
- §3.9 — revise — **mismatch** — link 5 fires only when link 3 actually moved ≥1 calendar — `amendments.py:79`
- §3.9 — insert — ambiguity — refund replacement does **not** copy `subject_visit_id`; five other fields null; unreviewable because born `ROUTED_SPONSOR` — `audit.py:121`, `derive.py:273`
- §3.9 — insert — ambiguity — `NO_ACTION` still increments the finding's and the study's `version` — `audit.py:104`
- §3.9 — revise — ambiguity — `run_date` is a `YYYY-MM-DD` string; `charges_aged_count` counts every re-stamped unbilled charge (version bumped) regardless of bucket change; job is unconditional — `ops.py:22,33,55`
- §5 table — insert — ambiguity — added `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `errors.py:84`

Verified unchanged-and-correct (no edit needed): all 5 roles and every endpoint's authorized-role set, all 37 validation-order priorities as implemented, the eight ledger formulas, posture clause order, both indirect-rounding orders, the invoice waterfall caps/credit tiering, aging bucket bounds, the five-link amendment cascade, the 201/200 split, and all 66 pre-existing error-code statuses.

### Orchestrator verification

`workspace/PRD_COMPLETED.md` exists, 433 lines / 93,980 chars, ends with the completed §5 error table (three new rows present). Pipeline complete.
