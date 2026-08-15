# Worklog — task_1566_campus_police_clery_act_reporting

## Step 1: Create Task Directory — 2026-08-13T21:35:00.000Z

Task directory `tasks/task_1566_campus_police_clery_act_reporting/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-13T22:22:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1566_campus_police_clery_act_reporting/` and lint clean.

### Files produced
- `SCAFFOLD.yaml` — §1.0–§1.7 (fixed response envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, RBAC). No `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:` (§1.8).
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:` (§1.9).

### Counts
| Metric | Count |
|---|---|
| Entities | 15 (CleryGeography, CampusSecurityAuthority, CSATrainingRecord, CSAReferralReport, IncidentReport, OffenseCount, SafetyAlert, DailyCrimeLogEntry, LogInspectionRequest, AnnualSecurityReport, StatisticLine, FireIncident, FireSafetyReport, ProgramReview, CorrectiveAction) |
| State machines | 12 (incl. cyclic reclassification loop on IncidentReport, fork+cycle on SafetyAlert, verification loop on ProgramReview, cyclic reject on CorrectiveAction, cyclic amend/republish on both reports) |
| Calculations | 9 (hierarchy resolution, geography double-count, ASR dual-variant compile, fire nested-rounding aggregation, dual-variant inspection window, business-day timeliness, 48h/24h alert deadlines, CSA certification window, penalty weighted scoring) |
| Validations | 29 (ordered priority 1–11 across auth/existence/state/safety/temporal/constraint/referential) |
| Endpoints | 70 (incl. `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z) |
| Errors | 26 |
| Roles | 6 (SystemAdmin, CleryCoordinator, PoliceChief, CampusSecurityAuthority [entity-backed], FederalReviewer, Anonymous; segregation-of-duties between coordinator and chief) |
| §1.8 instances | 18 (2 per rule × 9 rules, all structured with replayed setup chains) |
| §1.9 instances | 65 total: 60 active + 5 `excluded_because` stubs |

### Key difficulty features
- Dual-variant calcs on two domains (ASR PROVISIONAL vs FINAL; inspection-window CALENDAR_DATE vs ELAPSED_HOURS with a precomputed divergent example: same entry → FULFILLED immediately vs provisional due 2026-08-04T01:00:00Z)
- Combinatorial formulas in two modes: (a) hierarchy+exemption+geography double-count; (b) round-per-incident-then-sum fire damage (pinned: 100.50 + 100.50 → 202, not 201)
- Depth-3 cascade (unfound → log disposition → ASR statistics_stale → StatisticLine SUPERSEDED) and depth-2 fire finalize cascade (totals_stale → published report auto-UNDER_AMENDMENT)
- OCC on `IncidentReport.version` (classify) and `AnnualSecurityReport.version` (compile), both lint-compliant with `${var}` placeholders
- Two temporal-overlap rules with different interval semantics (closed integer year intervals vs half-open datetime windows)
- Two compensating invariants (ASR offense-count conservation across reclassify cycles; log-entry cardinality conservation)

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Additional audits passed: every error code referenced and exercised, all endpoint roles in RBAC, no duplicate instance names across both design files, no forbidden concurrency vocabulary.

## Step 3: Copy Shared Files — 2026-08-13T22:24:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1566_campus_police_clery_act_reporting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T23:05:00.000Z

NOTE: Resume run — the previous run's PRD.md was found truncated at §2.9 (125 lines, no §3/§4/§5, no worklog entry); it was deleted and regenerated from scratch.

Subagent summary (verbatim):

All checks pass. The PRD is complete and verified.

**Output:** `workspace/PRD.md` — 315 lines, ending correctly with the §5 error catalogue table (last line: `| ERR_ENTRY_NOT_PUBLIC | 403 |`).

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (all 6 roles with identity semantics), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Properties & OCC, 2.6 Reference Resolution & Validation Priority, 2.7 Precision & Rounding, 2.8 Date-Range & Field Constraints
- §3 Business Logic: 3.1 Geography Registry, 3.2 Incident Intake & CSA Referrals, 3.3 Classification & Offense Hierarchy, 3.4 Daily Crime Log & Public Inspection, 3.5 ASR Compilation, 3.6 Timely Warnings, 3.7 CSA Certification, 3.8 Fire Incidents & Fire Safety Report, 3.9 Program Reviews & Corrective Actions
- §4 Endpoint Definitions (70-row, 4-column table)
- §5 Error Code Catalogue (26-row, 2-column table)

**Coverage verification (all mechanical checks pass):**
- All 129 required identifiers present in backticks (139 entity fields + 57 endpoint input/query/path identifiers, deduplicated, plus common fields and pagination fields); three initial misses (`report_id`, `review_id`, `variant`) were fixed with targeted edits.
- All 26 error IDs, all 6 roles, all state values across the 12 state machines (57 transitions), and all 70 endpoint paths in the §4 table are present.
- All 9 calculations expressed in prose (hierarchy rank table, geography column mapping incl. ON_CAMPUS_RESIDENTIAL dual-increment, ASR compile 4-step pinned order with PROVISIONAL/FINAL variants, fire damage round-per-incident-then-sum with divergent provisional, dual-variant inspection window, business-day log timeliness, 48h/24h alert deadlines, CSA half-open certification window with adjacency rule, penalty scoring with repeat-doubling and 100-point escalation).
- Both OCC rules (`expected_incident_version` / `expected_report_version` → `ERR_STALE_VERSION` 412) stated; all cascade chains (unfound 3-link, reclassification staleness, fire totals_stale → auto-UNDER_AMENDMENT, verify → auto-advance) expressed.
- §3 path purity: zero HTTP methods or URL paths in §3 backticks.
- The withheld files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T23:20:00.000Z

Subagent summary (verbatim):

Generated complete test infrastructure for `task_1566_campus_police_clery_act_reporting` per the prd-bench-unit-test-generator skill.

**Files written:**

`test_helpers/` (9 files):
- `types.py` — 15 status/field enums + 16 entity TypedDicts
- `api_client.py` — `ApiClient(GenericApiClient)` with 76 methods covering every PRD §4 endpoint
- `api_errors.py` — 26 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators
- `factories.py` — 16 payload factories (input fields only)
- `constants.py` — thresholds (48h/24h/72h, 60-day window, pass score 80, escalation 100, severity weights)
- `test_users.py` — `TEST_USERS` for all six roles + `make_csa_headers(user_id)` for the entity-backed CSA role
- `fixtures.py` — composite fixtures across all tiers: incident state progression (draft→submitted→under-classification→classified→unfounded), CSA active/pending + referral with ownership-threaded headers, alert pipeline (pending→decided→authorized), ASR compiled/published, fire report compiled/published, program-review lifecycle through CLOSED, pending inspection-request setup, logical-clock helper
- `__init__.py` — barrel export

`test_suite/` (13 files): `conftest.py` + 12 numbered test files (geographies, CSA certification, referrals, incidents, classification, daily crime log, inspection requests, safety alerts, ASR, fire safety, program reviews, security/RBAC).

**Coverage:**
- Queue A (Difficulty): 18/18 instances, each with exactly 2 tests → 36 tests
- Queue B (Corner): 60/60 non-stub instances, each with 1 test → 60 tests
- Total: 96 test functions; all collect under pytest; all import against the framework package
- Docstring audit: all 96 docstrings carry verbatim PRD quotes (≥8-word substring grep-verified against PRD.md) and end with exactly one `Design:` tag resolving to a real instance; no skip/xfail markers; no scaffold references in generated code
- 5 `excluded_because:` stubs not translated; all cross-references verified to resolve (`vawa_and_referral_exemption_counted`, `residential_double_count_column`, `provisional_includes_under_reclassification`, `statistics_stale_set_on_unfound`, `derived_staleness_reconciled_on_recompile`)

**Instances skipped:** none. Every non-stub instance passed the PRD-first two-condition filter — the PRD contains verbatim rule-bearing prose for every asserted error id, threshold, transition, and side effect (including the two priority-pair instances, which PRD §2.6 covers with an explicit fixed priority order, and the dual-variant inspection instance, which PRD §3.4 covers with the exact 60-day/1440-hour divergence).

## Step 6: Generate Implementation — 2026-08-13T23:40:00.000Z

Subagent summary (verbatim):

Implementation complete and verified. Summary follows.

## Files written

All under `workspace/implementation/`:

- `start.sh` — guarded `pip install` (no-op once Flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry point, envelope error handlers (ApiError/404/405/500), clock endpoint, blueprint registration
- `core.py` — in-memory store (plain dicts, starts empty, no seeding), logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), `ApiError`, response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), `limit`/`offset`/`total_count`/`has_more` pagination (default 10, min 1, max 100), auth decorator (`X-User-ID`/`X-User-Role`, six roles), field validators, business-day math, half-up rounding, lazy CSA/record expiry
- `routes/` — `geographies.py`, `csas.py`, `referrals.py`, `incidents.py`, `alerts.py`, `crime_log.py`, `asrs.py`, `fires.py`, `reviews.py`

## Endpoint count

70 endpoints — every row of the scaffold §1.5 table (verified against the Flask URL map), including `POST /_clock/set_current_utc`.

## Verification

Two self-written smoke suites (~120 assertions) run against fresh `start.sh` boots: full lifecycle flows plus boundary cases (decide exactly at +48h on time, disseminate 1s late overdue, reopen exactly at +72h permitted, forward exactly at +24h not overdue, publish exactly Oct 1 on time, training-window adjacency, business-day entry/disposition timeliness, 60-day calendar-date vs 1440-hour provisional inspection windows, residential double-column counting, PROVISIONAL vs FINAL inclusion, OCC 412s, unfound/reclassification staleness cascades, repeat-finding doubling, auto-advance to UNDER_VERIFICATION, lazy LAPSED/EXPIRED). Both suites pass; a restart between runs confirmed state wipes clean (empty store, clock reset).

## Design decisions where the PRD admitted multiple interpretations

- **Training-window overlap checks all existing records**, including failed ones — both PRD §3.7 and the scaffold say "any existing record"; only *new passing* records trigger the check. A passing record for an `ACTIVE` CSA is rejected `ERR_INVALID_STATE` (state machine lists only PENDING_TRAINING/LAPSED as from-states); failing records are always recorded without state change.
- **Cascade-mutated entities bump `version`/`updated_at`** (log entries, statistic lines, ASRs, fire reports) per the §2.5 "every mutation" rule and the skill's cascade guidance.
- **`last_disposition_change_at` is null at entry creation** ("set on every disposition mutation" — creation is not a mutation); `disposition_update_overdue` is false on manual PATCHes (decision instant = PATCH time).
- **Input datetimes are echoed verbatim** (e.g. `occurred_at`), system timestamps use 3-fractional-digit ISO, and `valid_to`/`certification_expires_at` use the literal `(year+1)-09-30T23:59:59Z` form from the spec.
- **Statistic-lines default filter = current `statistics_version`** (not `status == CURRENT`), so lines flipped SUPERSEDED by the staleness cascade remain visible in the default view; `?statistics_version=N` retrieves old snapshots.
- **Fire report compile from UNDER_AMENDMENT keeps status UNDER_AMENDMENT** (only DRAFT/COMPILED go/stay COMPILED), preserving the republish path; "compiled at least once" for the staleness cascade = status != DRAFT.
- **Program review scoring fields are computed live** (`is_repeat_finding`, `weight`, `penalty_score`, `escalated`, `open_action_count`) so a later-closed review's finding codes immediately affect repeat detection, matching the "computed" field semantics.
- **`report_number` uses the year of `reported_at`** with a global 6-digit sequence; `entry_number` is a global `CL-<seq6>` sequence.
- **Missing required body fields → `ERR_INVALID_REQUEST` (400); present-but-empty `justification`/`decision_rationale` → 422/400** respectively per the priority ordering (shape validation at priority 3 precedes path resolution at priority 4, so a malformed body to a nonexistent path returns 400).
- **Alert reopen resets exactly the five fields the PRD lists** (`decision`, `decided_at`, `authorized_at`, `disseminated_at`, `closed_at`) plus both overdue flags; `decided_by`/`authorized_by`/`distribution_channels` are retained per the literal text.
- **`is_public` is derived live from the parent incident status**; since log entries only exist post-submit, `include_unfounded` (staff-only) is the only non-public case in practice.

## Step 7: Run Tests and Iterate — 2026-08-14T00:05:00.000Z

Subagent summary (verbatim):

All 8 rounds passed 96/96. The fixes are stable across all 8 parallel runs.

## Summary

- **Iterations run**: 2 (initial sweep + post-fix sweep)

- **Tests deleted**: None.

- **Fixes applied to `test_helpers/`**:
  - `constants.py` — `DEFAULT_CLOCK_UTC` changed from `"2026-08-01T00:00:00Z"` to `"2026-08-01T00:00:00.000Z"`. PRD §2.5 mandates "three fractional digits" for `created_at`/`updated_at`, so the test's expected format for those fields was incorrect (PRD §2.4's `2026-08-01T00:00:00Z` literal describes the instant, not the wire format).
  - `fixtures.py` — `get_log_entry_for_incident` and `list_log_for_incident` now pass `include_unfounded=true` so staff lookups surface entries whose parent incident is in a non-public status (DRAFT/WITHDRAWN/UNFOUNDED), matching PRD §3.4's "Staff callers may pass `include_unfounded` to surface entries the public cannot see". Previously the fixture failed on test_09's unfound-cascade assertion because the entry for the UNFOUNDED incident was hidden by the default filter.

- **Fixes applied to `test_suite/`**:
  - `test_05_classification.py` — added missing `create_unfounded_incident` to the `test_helpers` import; the test referenced the helper but never imported it (NameError at collection).

- **Fixes applied to `implementation/`**:
  - `core.py` — added `fmt_dt_short` and `now_iso_short` alongside the existing `fmt_dt`/`now_iso`. `fmt_dt` keeps PRD §2.5's mandated "three fractional digits" format and remains in use for `created_at`, `updated_at`, and `api_request_timestamp`. `fmt_dt_short` renders whole-second instants without fractional digits (matching PRD §2.4's literal style and PRD §3.7's `valid_to` example) for all other domain timestamps.
  - `routes/alerts.py` — switched `decision_deadline_at`, `decided_at`, `authorized_at`, `dissemination_deadline_at`, `disseminated_at`, `closed_at` to `fmt_dt_short`/`now_iso_short`.
  - `routes/crime_log.py` — switched `last_disposition_change_at`, `fulfilled_at`, `requested_at`, `due_at`, `provisional_due_at` to short formatters.
  - `routes/referrals.py` — switched `received_at` and `forwarded_at` to `now_iso_short`.
  - `routes/asrs.py` — switched `compiled_at`, `published_at`, `amendment_started_at` to `now_iso_short`.
  - `routes/fires.py` — switched `published_at` to `now_iso_short`.
  - `routes/incidents.py` — switched `classified_at` and the unfound cascade's `last_disposition_change_at` to `now_iso_short`.
  - `routes/csas.py` — removed the spurious `ERR_INVALID_STATE` gate that rejected passing training records when the CSA was already `ACTIVE`. PRD §3.7 says a passing record "recorded while the CSA is PENDING_TRAINING or LAPSED flips the CSA to ACTIVE" — it describes the transition, not a precondition. The gate was masking the PRD-required `ERR_TRAINING_WINDOW_OVERLAP` (HTTP 409) rejection on the overlap tests, and blocking legitimate re-certification on the adjacency test. Also reordered checks so the structural window-overlap rule (priority 9) fires before the field-level score-range check (priority 11) per PRD §2.6.

## Step 8: Finalize PRD — 2026-08-14T00:15:00.000Z

Subagent summary (verbatim):

**File produced**: `workspace/PRD_FINALIZED.md`

**Line counts**: PRD.md 314 → PRD_FINALIZED.md 316 (+2 lines, +0.64%).

### Changes (2 edits)

- **§2.5** — insert — New paragraph pinning the wire format of server-stamped domain timestamps: whole-second instants render without fractional digits (`2026-08-01T00:00:00Z` style), sub-second instants render with three fractional digits; echo fields (`reported_at`, `occurred_at`, `occurred_end_at`, `completed_at`, `valid_from`, `date_reported`, `date_occurred`) and copy fields (`opened_at` ← `created_at`, `certification_expires_at` ← `valid_to`) keep the source value unchanged — `implementation/core.py:99-114` (`fmt_dt_short`/`now_iso_short`), used at `routes/alerts.py:43,93,110,111,137,152`, `routes/crime_log.py:108,157,176-178,202`, `routes/referrals.py:48,103`, `routes/asrs.py:136,195,209,229`, `routes/fires.py:229`, `routes/incidents.py:306,371`; echo/copy behavior at `routes/incidents.py:104-106,169-170`, `routes/referrals.py:51-52`, `routes/fires.py:68`, `routes/csas.py:99,103,111`, `routes/reviews.py:89`.
- **§3.7** — revise — Extended the passing-training-record sentence to pin that a passing record recorded while the CSA is already `ACTIVE` is accepted and re-certifies (stays `ACTIVE`, refreshes `certification_expires_at` and `active_training_record_id`) — `implementation/routes/csas.py:109-114` (the Step 7 fix removed the spurious `ERR_INVALID_STATE` gate that had rejected this case).

### Step-7 items requiring no PRD edit

- `constants.py` clock literal → `.000Z`: test-side fix; PRD §2.5 already mandates three fractional digits for `created_at`/`updated_at`, and §2.4's literal describes the instant.
- `fixtures.py` `include_unfounded=true`: fixture bug; PRD §3.4 already pins staff `include_unfounded`.
- `test_05` missing import: pure test bug.
- `csas.py` check reorder (window-overlap priority 9 before score-range priority 11): already pinned by PRD §2.6's priority list.

### Per-edit pre-edit search log

**Edit 1 (§2.5 timestamp formats)**
- (a) Subject: wire rendering format of every timestamp field emitted by the server.
- (b) Paths enumerated and read: `core.py` (`fmt_dt` lines 92-96, `fmt_dt_short` 99-106, `now_iso`/`now_iso_short` 109-114, `mint`/`touch` 180-194, `make_meta` 158-162); `app.py:41-48` (clock `current_utc` echoes raw); `routes/alerts.py` (all six alert timestamps); `routes/crime_log.py` (`last_disposition_change_at`, `requested_at`, `due_at`, `provisional_due_at`, `fulfilled_at`); `routes/referrals.py` (`received_at`, `forwarded_at`, echoed `occurred_at`/`occurred_end_at`); `routes/incidents.py` (`classified_at`, unfound-cascade `last_disposition_change_at`, echoed `reported_at`/`occurred_at`/`occurred_end_at`, copied `date_reported`/`date_occurred`); `routes/asrs.py` (`compiled_at`, `published_at`, `amendment_started_at`); `routes/fires.py` (`published_at`, echoed `occurred_at`); `routes/csas.py` (echoed `completed_at`/`valid_from`, hard-formatted `valid_to` line 18, copied `certification_expires_at` line 111); `routes/reviews.py:89` (`opened_at` = `created_at`, renders `.000Z` even at whole seconds); `routes/geographies.py` (no domain timestamps).
- (c) Wording adjustments: scoped the rule to "timestamp fields **on resources**" so it cannot be read to cover `meta.api_request_timestamp` (which §2.2 pins at three fractional digits and impl always renders via `now_iso`); added the echo-field and copy-field carve-outs because `opened_at` (copies `.000Z`-style `created_at`) and the seven client-echo fields would otherwise falsify a universal "whole-second renders without fractional digits" claim; field lists verified exhaustively against every route file.

**Edit 2 (§3.7 ACTIVE re-certification)**
- (a) Subject: effect of a passing training record when the CSA is already `ACTIVE`.
- (b) Paths enumerated and read: `routes/csas.py:68-115` (`create_training_record`: INACTIVE gate at 77-78, overlap check 87-94 applies to passing records regardless of CSA status, score range 96-97, certification refresh 109-114), `core.py:367-390` (`refresh_csa`/`refresh_training_record` lazy lapse, unaffected), `routes/referrals.py:35-39` (ACTIVE requirement for filing, unaffected), PRD endpoint table row "a passing score activates or re-certifies" (already consistent).
- (c) Wording adjustments: phrased as "likewise accepted and re-certifies" without repeating the overlap guard, matching the PRD's existing style of describing transitions assuming validation passes (the overlap rule in the prior paragraph already gates all new passing records), avoiding a false claim that acceptance is unconditional.

## Step 9: PRD Completeness Scan — 2026-08-14T00:25:00.000Z

Subagent summary (verbatim):

Step 9 complete. `workspace/PRD_COMPLETED.md` was produced by copying `PRD_FINALIZED.md` and applying 23 minimal inline edits (the 25 numbered bullets below include sub-parts).

**Stats**
- Source: `PRD_FINALIZED.md` — 316 lines, 54,181 chars. Output: `PRD_COMPLETED.md` — 316 lines, 58,473 chars. Char delta: +4,292 (no lines added or removed; all edits are in-paragraph inserts/revisions, no new sections).
- Counts: 21 ambiguity-pins, 2 mismatch-revisions.

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl file:line)

1. §2.3 Pagination — insert — ambiguity — non-integer/out-of-bounds `limit`/`offset` yield `ERR_VALIDATION_FAILED` 422 — core.py:336-357
2. §2.3 Pagination — insert — ambiguity — list sort ties broken by stable creation order — core.py:201-202
3. §2.4 Logical clock — revise — ambiguity — response echoes the client's `to_iso8601` string unchanged as `current_utc` (not a canonical re-render) — app.py:44-48
4. §2.6 Validation priority — revise — ambiguity — request-shape validation runs as soon as the body is read, so it can precede path resolution on body-first operations — incidents.py:248-275 (classify), alerts.py:77-89 (decide), incidents.py:352-356 (unfound)
5. §3.1 Geographies — insert — ambiguity — PATCH accepts any combination of `name`/`is_residential_facility`/`status`; supplied fields replace, omitted unchanged — geographies.py:53-86
6. §3.2 Incident intake — insert — ambiguity — `report_number` year is the calendar year of `reported_at`, from a per-server incident counter — incidents.py:101-103
7. §3.2 Incident list — insert — ambiguity — non-integer `report_year` filter matches nothing rather than erroring — incidents.py:137-143
8. §3.2 Referral filing — revise — ambiguity — an `X-User-ID` resolving to no registered CSA is also rejected with `ERR_CSA_NOT_CERTIFIED` 422 — referrals.py:35-39
9. §3.2 Referral list — insert — ambiguity — for a CSA caller, `csa_id` narrows within their own reports, never widens — referrals.py:69-73
10. §3.3 Submission — revise — mismatch — submit is allowed for `CleryCoordinator` **or `PoliceChief`** (PRD said only coordinator) — incidents.py:156
11. §3.3 Classify — insert — ambiguity — `offense_counts` element shape is validated with `ERR_INVALID_REQUEST` 400 before state/OCC checks — incidents.py:252-275
12. §3.3 Offense fields — insert — ambiguity — `referred_persons` is never negative (`ERR_VALIDATION_FAILED` 422) — incidents.py:302-303
13. §3.3 Hierarchy — insert — ambiguity — log-entry `nature` label source pinned: primary type, else lowest-rank earliest-submitted COUNTED (all-exempt) row, else "Unclassified" — incidents.py:217-242, 313-317
14. §3.3 Offense listing — insert — ambiguity — `offense-counts` list returns current rows in classify-call submission order — incidents.py:409-414
15. §3.3 Unfound cascade — insert — ambiguity — unfounding also resets `is_clery_reportable` to false — incidents.py:388
16. §3.3/§3.5 Reclassification vs unfound staleness — insert — ambiguity — reclassification cascade touches only `COLLECTING`/`UNDER_AMENDMENT` ASRs, unfound cascade staleness applies regardless of ASR status — incidents.py:319-329 vs 376-383
17. §3.4 Log entry birth — insert — ambiguity — new entries also start with `general_location` null and `last_disposition_change_at` null — incidents.py:166-173
18. §3.4 Disposition endpoint — revise — mismatch — `UNFOUNDED` target is rejected with `ERR_INVALID_STATE` 409 (PRD implied 422); unknown disposition strings get `ERR_VALIDATION_FAILED` 422 — crime_log.py:97-106
19. §3.4 Public transparency — insert — ambiguity — `is_public` derived from parent incident status at read time; truthy `include_unfounded` (`true`/`1`/`yes`, case-insensitive) shows **all** non-public entries to staff, absent/other values restrict staff to public entries; date filters compare date portion of `date_occurred` — crime_log.py:31-75
20. §3.5 Statistic-line filters — insert — ambiguity — non-integer `statistics_version` filter matches nothing — asrs.py:150-159
21. §3.6 Alert birth — insert — ambiguity — full null-field set at creation pinned (`decision_rationale`, `decided_by`, `authorized_by`, `dissemination_deadline_at`, `distribution_channels` also null; both overdue flags false) — alerts.py:37-55
22. §3.6 Alert decide/reopen — insert — ambiguity — blank `decision_rationale` → `ERR_INVALID_REQUEST` 400; reopen records `reason` as `reopen_reason` and deliberately does NOT reset `decision_rationale`/`decided_by`/`authorized_by`/`distribution_channels` or the computed deadlines — alerts.py:80-84, 161-184
23. §3.7 CSA training — insert — ambiguity — training for an `INACTIVE` CSA → `ERR_INVALID_STATE` 409; every record born `ACTIVE`; `valid_to` renders in whole-second style — csas.py:76-78, 98-107, 17-18
24. §3.8 Fire compile — insert — ambiguity — compile from `DRAFT`/`COMPILED` lands in `COMPILED`; compile during `UNDER_AMENDMENT` stays `UNDER_AMENDMENT` — fires.py:211-214
25. §3.9 Corrective actions — insert — ambiguity — action born `OPEN` with null `resolution_summary`/`verification_note`, `rejection_count` 0; `is_repeat_finding`/`weight` and the review's `open_action_count`/`penalty_score`/`escalated` are derived at read time from the live action set (`OPEN`+`SUBMITTED` count as open); `note` stored on the review as `return_note` — reviews.py:42-64, 171-184, 145-146

One deliberate residual note: impl stores `is_public: True` on the stored entry at creation (visible only if a DRAFT-parent entry were serialized before any submit, which the derived-read serialization prevents) — the derived-at-read semantics pinned in change 19 fully cover observable behavior.

PIPELINE COMPLETE — Steps 1-9 done. Final artifact: workspace/PRD_COMPLETED.md.
