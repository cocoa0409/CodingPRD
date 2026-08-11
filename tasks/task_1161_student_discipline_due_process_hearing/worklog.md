# Worklog — task_1161_student_discipline_due_process_hearing

## Step 1: Create task directory — 2026-08-11T05:31:28.921Z

Pre-assigned output folder `tasks/task_1161_student_discipline_due_process_hearing` with `workspace/` subdirectory already existed (creation handled externally). Auto-index scan skipped per instruction. Verified directory structure; no scaffold/PRD/test/implementation artifacts present yet.

## Step 2: Generate scaffold (subagent) — 2026-08-11T06:35:22.644Z

Scaffold generation complete for task 1161 (Student Discipline & Due-Process Hearing). No sibling task directories were inspected — the design was derived purely from the scenario text plus the skill specification.

**Files written** (all verified on disk):
- `/home/ubuntu/github/CodingPRD/tasks/task_1161_student_discipline_due_process_hearing/SCAFFOLD.yaml` — 73,634 bytes (§1.0–§1.7; neither design key present)
- `/home/ubuntu/github/CodingPRD/tasks/task_1161_student_discipline_due_process_hearing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 93,706 bytes (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1161_student_discipline_due_process_hearing/SCAFFOLD_CORNER_DESIGN.yaml` — 155,949 bytes (single top key `scaffold_corner_design`)

**Counts**: 14 entities, 53 endpoints, 36 error codes, 11 state machines, 5 calculations, 11 validation priority rows, 5 roles, 2 OCC concurrency rules. Difficulty instances (§1.8): 18 (2 per rule × 9 rules). Corner instances (§1.9): 67 total = 57 active + 10 `excluded_because` stubs; 850 structured API calls replayed by the linter.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Two issues were found and fixed during iteration: unquoted `errors[...]`/`$.data[N].x` tokens breaking YAML flow parsing, and one `FK_REVERSE_UNREACHABLE` (case→offense-code) fixed by adding `offense_code_id?` to `GET /cases`.

**Design highlights** (beyond-Expert target): compliance/audit archetype with workflow-orchestration secondary; flat topology; segregation-of-duties role model (referrer ≠ classifier ≠ appeal decider ≠ hearing officer). The nine difficulty rules are instantiated with the required differentiations: dual-variant calcs in case-history vs aggregate-report domains; combinatorial modes (a) sanction band/override/threshold branching and (b) pinned divide-then-round risk ratio (0.50 vs naive 0.52 fixture); cyclic machines on DisciplineCase (appeal reversal) and Conference (NO_SHOW loop); depth-3 cascade (appeal→case→notice→conference) vs depth-2 (hearing→case→student enrollment); priority pairs {state, temporal} on appeals vs {safety, constraint} on placements; boundaries on the strict >10 MDR day count vs the inclusive 5-day appeal deadline; cross-entity gates Case←MDR and ReEntryPlan←AltEdPlacement; half-open officer-calendar overlap vs closed-interval aggregate site capacity; and compensating invariants on the suspension-day ledger (confirm +6 → expunge → 0) and site seat count (+1 → complete → 0). All deadlines run on a declared logical clock (`POST /_clock/set_current_utc`, default 2026-05-01T00:00:00Z).

## Step 3: Copy shared files — 2026-08-11T06:35:42.160Z

Copied `./INSTRUCTION.md` → `tasks/task_1161_student_discipline_due_process_hearing/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD (subagent) — 2026-08-11T06:49:27.670Z

PRD generation complete. Output verified on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1161_student_discipline_due_process_hearing/workspace/PRD.md` (51,467 bytes).

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1161_student_discipline_due_process_hearing/workspace/PRD.md`
**Size**: 51,467 bytes | **Words**: ~7,098 | **Sections**: 25 headings (title + §1 + 10 §2 subsections + 9 §3 subsections + §4 + §5), with a 53-row endpoint table and a 36-row error catalogue.

**Document design**: §2 organized around domain concerns (logical clock, suspension-day ledger, OCC, an 11-rung validation-precedence ladder with pinned intra-rung ordering, precision rules); §3 grouped by workflow lifecycle in 9 subsections (enrollment/matrix → referral/classification → sanction/discretion → notice-conference-appeal → expulsion hearing/evidence → MDR → alt-ed placement/re-entry → closure/expungement → disproportionality reporting). §2.2 emitted verbatim from the canonical block. No pseudocode anywhere — all formulas (occurrence counting under both ROLLING_365 and ACADEMIC_YEAR variants, band lookup with lesser-of-index-and-3 clamp, MDR strict-greater-than-10 trigger, IDEA cap, half-open officer overlap, 730-day inclusive expungement wait, full-precision-divide-then-round report metrics) rendered as reconstructible prose.

**Zero-silence audit (Hard Contracts)**:
- **Contract 1 (Field-Name Coverage): PASS** — 90 required identifiers (all `entities[].fields` + all endpoint input/query/output identifiers incl. `to_iso8601`, `current_utc`, `expected_case_version`, `rationale`, `ruling`, `groups_evaluated`, `risk`, `risk_ratio`, `share_gap`), 90 present in backticks, 0 missing. (An initial false negative was traced to my audit regex mispairing backticks across §2.2's fenced JSON blocks, not to the PRD; stripping fences confirmed full coverage.)
- **Contract 2 (Rule Coverage): PASS** — 30/30 targeted rule checks pass: both OCC rules with write-endpoint framing + `ERR_STALE_VERSION`/412, all 14 DisciplineCase transitions incl. self-loops, all cascade chains (REVERSED 3-link, REMANDED, EXPULSION_ORDERED 2-link, notice-void → conference-cancel, expungement ledger compensation), validation ladder with priority ordering and cap-before-range, all `applies_to` scopes (notice + placement MDR gates), all 36 error IDs matched to trigger prose, all state/enum values present, sibling-branch symmetry across appeal/hearing/placement/MDR/re-entry/expungement/conference forks and both dual-variant calculations.
- **Contract 3 (§3 Path Purity): PASS** — 434 backticked tokens in §3 scanned; 0 path tokens, 0 bare HTTP-method tokens, 0 method+path tokens.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never read, and no other task directories were accessed.

## Step 5: Generate unit tests (subagent) — 2026-08-11T07:26:11.822Z

Done. Test generation for task_1161 is complete and verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1161_student_discipline_due_process_hearing/`)

**test_helpers/ (Stage 1, 9 files, ~66 KB)**
- `__init__.py` (994 B) — barrel export: framework generics + PRD-specific code
- `types.py` (8,391 B) — 20 status/field enums, 14 entity TypedDicts; OffenseCode/SanctionBand carry only `id`+`created_at` (no `updated_at`/`version`)
- `api_client.py` (8,780 B) — `ApiClient(GenericApiClient)` with one method per endpoint (44 endpoints incl. `/_clock/set_current_utc`)
- `api_errors.py` (3,934 B) — all 35 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (8,765 B) — per-entity structural assertions + `assert_student_ledger_invariant`
- `factories.py` (7,011 B) — payload factories, input fields only
- `constants.py` (1,571 B) — thresholds (cap 10, MDR 10/10, 365-day window, 730-day wait, rounding decimals)
- `test_users.py` (2,491 B) — shared role headers + `make_*_headers` builders (guardian → `guardian_id`, officer → `hearing_officer_id` threading)
- `fixtures.py` (25,186 B) — composite chains: notice-issued / confirmed / closed cases, appeal-filed, expulsion-referred → HELD → EXPULSION_ACTIVE, auto-MDR setup, placements/re-entry, disproportionality scenario

**test_suite/ (Stage 2, 12 files, ~124 KB)** — `conftest.py` + `test_01_students` … `test_11_rbac_security`

## Test counts
- Queue A (Difficulty): **36 tests** — all 18 instances × 2, every instance ≥2 ✓
- Queue B (Corner): **57 tests** — all 57 non-stub instances × 1 ✓
- Total: **93 tests**, every one tagged with exactly one `Design:` line resolving to a real instance (audit script: AUDIT CLEAN)

## Skipped instances (stubs — not translated, cross-references verified to resolve)
All 10 `excluded_because:` stubs: `disproportionality_computed_read`, `error_mdr_incomplete_on_notice`, `error_site_capacity_on_placement`, `error_invalid_state_on_closed_case_appeal`, `error_placement_not_active_on_plan_activation`, `error_appeal_window_closed_boundary`, `appeal_reversal_cascade_coverage`, `dual_variant_calculation_coverage`, `mdr_threshold_rate_trigger_coverage`, `derived_field_reconciliation_coverage`. No non-stub instance was skipped.

## Two-reader adjustments (assertions narrowed, tests kept)
- Absolute `version == 1` on creation is not PRD-pinned ("increments with every mutation"); version assertions use relative +1 increments ("increments the case `version` by one" is verbatim for classify/sanction).
- Report rows: only PRD-named fields asserted (`risk`, `risk_ratio`, `share_gap`, `groups_evaluated`); rows located via `demographic_group` (the only group identifier the PRD provides); unpinned `enrolled`/`disciplined` row keys not asserted.
- Several expulsion-chain recipes in the design YAML had packet service ~1 day before a hearing start (violating the PRD's 2-day evidence lead and so impossible to set up); setup timestamps were shifted earlier (referral 05-01, hearing 05-05, second chain 05-06/05-10) keeping clocks forward-only and all asserted literals unchanged.

## Verification
- `python3 -m py_compile` over all 21 `.py` files: **ALL FILES COMPILE OK**
- Import smoke test (`PYTHONPATH=. python3 -c "import test_helpers; import test_suite.conftest"`): OK
- PRD-citation sweep: every quoted citation (≥4 words, elisions fragment-checked) survives literal grep of `workspace/PRD.md`: **0 failures**

## Step 6: Generate implementation (subagent) — 2026-08-11T07:26:11.822Z

Implementation complete. Summary:

## Files generated (in `/home/ubuntu/github/CodingPRD/tasks/task_1161_student_discipline_due_process_hearing/workspace/implementation/`)

| File | Size | Role |
|---|---|---|
| `start.sh` (exec) | 396 B | Guarded pip install (`import flask` check), `exec python3 app.py`, foreground |
| `requirements.txt` | 16 B | `flask>=3.0,<4.0` |
| `app.py` | 2120 B | Flask assembly, envelope-wrapped error handlers (ApiError/404/405/400/500) |
| `db.py` | 2045 B | In-memory store (empty at boot, no seeding), logical clock (default `2026-05-01T00:00:00Z`), `stamp`/`touch` (updated_at + version on every mutation; OffenseCode/SanctionBand are "light" — no version/updated_at) |
| `errors.py` | 2611 B | ApiError + full 36-entry error catalog |
| `response.py` | 1034 B | Envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more` |
| `middleware.py` | 2846 B | `X-User-ID`/`X-User-Role` auth (401), role check (403), limit/offset parsing (10/1/100/0) |
| `util.py` | 1813 B | ISO-8601 parse/format (3 fractional digits), academic-year bucketing |
| `routes/` (12 modules + common) | ~43 KB | clock, students, offense_codes (+bands), cases (classify/sanction with OCC, notices, confirm, close, refer-expulsion), conferences, appeals, hearings (+evidence/rule/serve/convene/decision), mdr, alt_ed (sites+placements), reentry, expungement, reports |
| `services/calc.py` | 6047 B | ROLLING_365 + ACADEMIC_YEAR occurrence counts, band lookup, ledger recompute, MDR auto-create, seats_occupied, disproportionality (full-precision divide, round-half-up 4dp/2dp) |
| `services/cascade.py` | 2139 B | Appeal REVERSED/REMANDED notice-void + conference-cancel chain, hearing decision → case/student cascade, expungement approval cascade |

## Route count
53 (method, path) pairs registered — matches SCAFFOLD.yaml §1.5 exactly (the 54th Flask rule is the built-in `/static` route).

## Verification
- `python3 -m py_compile` over all 24 `.py` files: **COMPILE OK**
- Boot smoke (`PORT=18731 bash start.sh`, background, curl, kill): server binds `0.0.0.0`, answers HTTP in <2s; fresh-reboot check confirms empty store and default clock after relaunch.
- **31-check functional smoke** (auth 401/403, schema 400, dup code/band, SoD 403, OCC 412, classify/sanction flows, cap 422-before-range 422, override, notice/conference/appeal gates, REVERSED cascade voiding notice, pagination meta): all pass.
- **48-check deep smoke** (hearing window/overlap/already-open, evidence lock, convene, EXPULSION_ORDERED → case EXPULSION_ACTIVE + student ALT_ED_PENDING, MDR gates → placement → IN_ALT_ED → re-entry → completion → ENROLLED → close, 730-day expungement → EXPUNGED + ledger reset, disproportionality report with exact values — risk 1.0/0.0, ratio 1.0/0.0, share_gap 0.5/-0.5): all pass.

One bug found and fixed during smoke: classify/sanction were not assigning the new `status` (CLASSIFIED / SANCTION_PROPOSED).

Judgment calls on PRD-internal ambiguities (all following PRD §2.9's explicit ladder over narrative order): temporal rung-10 errors surface before rung-11 uniqueness/capacity errors on the same endpoint (reschedule deadline before attempt-cap; serve-packet deadline before packet-empty; hearing window before already-open/overlap; placement capacity before already-active); SoD (rung 4) before body-FK existence (rung 5); nested collection GETs paginate with the same limit/offset defaults as top-level lists.

**Orchestrator route-parity verification (pre-sweep)**: independent diff of SCAFFOLD.yaml §1.5 (method, path) pairs vs `@bp.get/@bp.post` registrations in implementation/ — 53 scaffold endpoints, 53 impl routes, 0 missing, 0 extra.

## Step 7: Run tests and iterate (subagent) — 2026-08-11T07:38:00.000Z

## Summary

- **Iterations run**: 2 (first sweep had 6 consistent failures; second sweep after fixes passed all 8 rounds at 93/93).
- **Tests deleted**: None.
- **Fixes applied to `test_helpers/`**: None.
- **Fixes applied to `test_suite/`**:
  - `test_suite/test_04_notice_conference_appeal.py` — added `create_sanctioned_case` to the `from test_helpers import (...)` block. The function is defined in `test_helpers/fixtures.py` and re-exported via the barrel wildcard, but the test referenced it without importing it (NameError). 
  - `test_suite/test_07_manifestation_determination.py::test_mdr_manual_create_while_open_returns_409` — restructured setup. The original setup used `setup_case_with_auto_mdr`, which leaves the case in `SANCTION_PROPOSED` (not on the expulsion track). Per PRD §3.6 ("The manual door ... may open a determination for an expulsion-track case") and §2.9 rung 11 ("manual-determination applicability (`ERR_MDR_NOT_APPLICABLE`) with uniqueness (`ERR_MDR_ALREADY_OPEN`)"), applicability is checked first, so the implementation correctly returned `ERR_MDR_NOT_APPLICABLE`. The fix uses `setup_expulsion_referred_case` (EXPULSION_REFERRED, disability_status SECTION_504) and first opens one manual MDR (success, status PENDING) so the second attempt's uniqueness rung fires `ERR_MDR_ALREADY_OPEN`. Also added `setup_expulsion_referred_case` to the imports.
- **Fixes applied to `implementation/`**:
  - `workspace/implementation/util.py` — split `fmt()` into two: `fmt()` now emits ISO 8601 UTC at second granularity (`2026-05-01T00:00:00Z`, matching the PRD's general "All timestamps ... are ISO 8601 UTC" and the PRD's own examples like the default clock `2026-05-01T00:00:00Z`); a new `fmt_ms()` keeps the three-fractional-digit form (`...T00:00:00.000Z`) which the PRD §2.2/§2.5 explicitly requires only for `api_request_timestamp` and `created_at`. `fmt_meta_ts()` now uses `fmt_ms()`.
  - `workspace/implementation/db.py` — `serialize()` now uses `fmt_ms()` for the `created_at` field (PRD §2.5 line 89 explicitly demands three fractional digits) and `fmt()` for every other business timestamp (`scheduled_at`, `filed_at`, `closed_at`, `appeal_deadline`, `issued_at`, `proposed_at`, `updated_at`, etc.), which the PRD specifies only as "ISO 8601 UTC" and consistently renders at second granularity in its own prose examples.

**Orchestrator disk verification**: all 8 `results.{1..8}.json` present (26 KB each), every round `passed: 93, total: 93, failed: 0` — ALL 8 ROUNDS PASS.

## Step 8: Finalize PRD (subagent) — 2026-08-11T07:43:36.765Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1161_student_discipline_due_process_hearing/workspace/PRD_FINALIZED.md` written.

## Exit summary

**Line counts / delta**: PRD.md = 308 lines, PRD_FINALIZED.md = 308 lines (0% line-count delta; exactly one line — line 125, §2.10 — revised in place).

### Changes (one edit total)

- **§2.10** — **revise** — Split the closing timestamp sentence: kept "All timestamps in request and response bodies are ISO 8601 UTC" verbatim, then pinned that the server renders every timestamp at second granularity (e.g. `2026-05-01T00:00:00Z`) with exactly two three-fractional-digit exceptions (`api_request_timestamp` per §2.2, `created_at` per §2.5), explicitly covering `updated_at`, all business timestamps (`proposed_at`, `issued_at`, `scheduled_at`, `filed_at`, `decided_at`, `confirmed_at`, `closed_at`, deadline fields) and the clock capability's `current_utc`; kept the midnight day-granularity clause verbatim — impl: `workspace/implementation/util.py:16-40` (fmt/fmt_ms/fmt_meta_ts), `workspace/implementation/db.py:84` (serialize: `fmt_ms` for `created_at`, `fmt` for all else), `workspace/implementation/response.py:10`, `workspace/implementation/routes/clock.py:20`.

### Step-7 items with no PRD edit (with rationale)

- `test_04_notice_conference_appeal.py` import fix — pure fixture bug (NameError on `create_sanctioned_case`); zero behavioral content.
- `test_07` MDR manual-create-while-open restructure — test was wrong, implementation was already PRD-conformant: §2.9 rung 11 already lists "manual-determination applicability (`ERR_MDR_NOT_APPLICABLE`) with uniqueness (`ERR_MDR_ALREADY_OPEN`)" and §3.6 narrates the same order; `mdr.py:27-34` matches. PRD already determines the behavior → prose kept verbatim per method.

### Per-edit pre-edit search log (NO-NEW-MISMATCH)

**Edit 1 (§2.10 timestamp granularity)**:
- (a) **Subject**: server-side rendering granularity of every timestamp appearing in a response body.
- (b) **Impl paths enumerated and read/grepped**: `implementation/util.py` (fmt = second-granularity, fmt_ms = three fractional digits, fmt_meta_ts → fmt_ms) — read; `implementation/db.py:75-89` `serialize()` (`created_at`→fmt_ms, every other datetime→fmt) — read; `implementation/response.py` `_meta()` used by both `success`/`success_list` and `error_response` (`api_request_timestamp`→fmt_meta_ts) — read; `implementation/routes/clock.py:20` (`current_utc`→fmt) — read; all ~30 `serialize(...)` call sites across `routes/{students,cases,conferences,appeals,hearings,mdr,alt_ed,reentry,expungement,offense_codes,common}.py` — grepped, confirming every entity datetime field (`updated_at`, `date_of_birth`, `incident_date`, `proposed_at`, `issued_at`, `appeal_deadline`, `conference_deadline`, `scheduled_at`, `filed_at`, `decided_at`, `confirmed_at`, `closed_at`, `referred_to_expulsion_at`, `scheduled_start/end`, `packet_served_at`, `due_at`, `meeting_at`, `completed_at`, `start_date`, `planned_end_date`, `actual_end_date`, `conference_date`, `last_case_closed_at`) renders at second granularity; `routes/reports.py` — read, response carries no datetimes; `services/calc.py` — grepped, datetimes are compute-only, never rendered; `errors.py`, `middleware.py`, `app.py` — read, render no timestamps of their own (error bodies flow through `error_response`→`_meta`→fmt_ms). Test evidence: `test_09_closure_expungement.py:27` asserts exact second-granularity equality `closed_at == "2026-05-13T00:00:00Z"`; `test_helpers/assertions.py` checks only ISO-8601-ness.
- (c) **Wording adjustments**: (i) kept the original request-and-response ISO 8601 clause verbatim as its own sentence so request-side parsing acceptance (`parse_dt` accepts offsets/date-only/fractional input) is not narrowed — the pin is scoped to what "the server renders"; (ii) named exactly the two verified `fmt_ms` exceptions rather than a blanket rule; (iii) every field enumerated in the new sentence was individually verified against the `fmt` path; (iv) §2.2's three-fractional-digit `api_request_timestamp` example and §2.4's second-granularity default-clock example both remain consistent with the new sentence, so no companion edits were needed.

## Step 9: Complete PRD (subagent) — 2026-08-11T07:55:27.701Z

Orchestrator note: the first Step 9 subagent completed a full PRD-vs-implementation scan (90+ numbered findings cataloged, final 12-item edit plan produced) but its turn was cut off by output size before applying edits — PRD_COMPLETED.md existed on disk only as a byte-identical copy of PRD_FINALIZED.md (confirmed by `diff -q`: IDENTICAL). Per protocol, disk was measured before re-running, and a bounded follow-up subagent was spawned to apply exactly the prior scan's verified edit plan. The scan's no-change verdicts were also preserved verbatim in the follow-up prompt. Follow-up exit summary below.

Exit summary:

**File verification**
- Source: `workspace/PRD_FINALIZED.md` — 308 lines, 51,944 chars.
- Edited: `workspace/PRD_COMPLETED.md` — 308 lines, 54,537 chars (char-delta **+2,593**; line count unchanged, all edits in-paragraph). Files verified to differ (`cmp`: DIFFERS); 16 diff hunks at lines 78, 89-91, 113, 116, 125, 131, 149, 175, 179, 181, 185, 187, 191, 195, 203, 205 — exactly the 12 planned change sites.

**Counts**
- Ambiguity-pins: 15
- Mismatch-revisions: 3 (items 5, 6, 10a — the midnight-storage corrections)

**Changes (one bullet per sub-edit)**
- §2.3 — insert — ambiguity — creation-timestamp ties broken by insertion order; `limit`/`offset` type-and-range rejection with `ERR_INVALID_REQUEST`; enum filter values validated, identifier filters exact-match without existence check — middleware.py:60-89; db.py:69-72
- §2.5 — revise — ambiguity — `version` pinned to begin at 1 at creation; `created_at`/`updated_at` pinned as stamped from the §2.4 logical clock — db.py:50-60
- §2.9 rung 3 — insert — ambiguity — scoping entity must resolve before any ownership comparison; unresolvable identifier surfaces `ERR_NOT_FOUND` first — routes/common.py:8-17; routes/expungement.py:28-33
- §2.9 rung 6 — insert — ambiguity — request body must be a JSON object when present; missing body treated as empty object — middleware.py:44-52
- §2.10 — revise — mismatch — day-granularity inputs accept ISO dates or timestamps (date-only → midnight UTC, timestamps stored as supplied); day-interval comparisons read the calendar date; `actual_end_date` clock-stamped, not day-granularity — util.py:43-61; routes/alt_ed.py:66-71; routes/students.py:23
- §3.1 — revise — mismatch — `date_of_birth` re-parenthesized as ISO date-or-timestamp with date-only stored at midnight per §2.10 — routes/students.py:23,45
- §3.3 — insert — ambiguity — in-range justification not retained; in-range adjustment clears retained justification to empty — routes/cases.py:211
- §3.5 — insert — ambiguity — decision outcome becomes the hearing's status; register's status filter therefore accepts EXPULSION_ORDERED/NOT_EXPELLED — routes/hearings.py:218
- §3.6 — insert — ambiguity — manual door's "applicable track" pinned to EXPULSION_REFERRED or EXPULSION_ACTIVE status — routes/mdr.py:28-32
- §3.6 — insert — ambiguity — scheduling performs no `meeting_at`-vs-`due_at` check; only completion is deadline-checked — routes/mdr.py:49-58
- §3.6 — insert — ambiguity — MANIFESTATION_YES cap adjusts `proposed_sanction_days` only, does not recompute `mdr_required` — routes/mdr.py:80-88
- §3.7 — revise — mismatch — placement dates now "ISO 8601 day values stored per §2.10" instead of "day-granularity values at midnight UTC" — routes/alt_ed.py:66-71
- §3.7 — insert — ambiguity — site creation response also carries `seats_occupied` (zero for a fresh site) — routes/alt_ed.py:26-41
- §3.7 — revise — ambiguity — re-entry plan `conditions` pinned as an ordered (possibly empty) list of strings — routes/reentry.py:25
- §3.8 — insert — ambiguity — placement-free expulsion case satisfies the every-placement closure gate vacuously and may close — routes/cases.py:309-311
- §3.9 — revise — ambiguity — `academic_year` must name two consecutive years (second = first + 1), else `ERR_INVALID_REQUEST` — routes/reports.py:18-20; util.py:78-88
- §3.9 — revise — ambiguity — enrolled count covers every student record with the group, regardless of `enrollment_status` — services/calc.py:140-188
- §3.9 — insert — ambiguity — `results` row keys pinned (`demographic_group`, `enrolled`, `disciplined`, `risk`, `risk_ratio`, `share_gap`) and row order pinned to the §3.1 enumeration — routes/reports.py; services/calc.py

Not touched per the no-change verdicts: §2.7 ledger-recompute sentence, unmatched-route 404/405 and ERR_INTERNAL 500, empty-string descriptions, sanction negative-days prose, and the report window's "through June 30" phrasing.
