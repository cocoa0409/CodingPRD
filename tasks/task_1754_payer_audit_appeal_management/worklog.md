# Worklog — task_1754_payer_audit_appeal_management

## Step 1: Create task directory — 2026-08-14T14:30:00.000Z

Pre-assigned directory `tasks/task_1754_payer_audit_appeal_management/` with `workspace/` subdirectory (treated as DONE per orchestration args; no index scan performed).

## Step 2: Generate scaffold — 2026-08-14T14:30:39.000Z

Scaffold generation complete. All three artifacts are written and the skill's linter reports a clean verdict.

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design` (§1.9)

### Counts

- **Entities: 12** — Payer, IssueCode, AuditCase, AuditClaimLine, Appeal (self-referential level chain), EvidencePacket, PacketItem, RecoupmentDemand, Remittance, OffsetTransaction, CorrectiveActionPlan, AuditCaseEvent (immutable log)
- **State machines: 10** — cyclic (RecoupmentDemand hold/release, CAP effectiveness loop), compound-with-revert (EvidencePacket), auto-transition sweeps (missed deadline, line finalization), lazy appeal expiry
- **Endpoints: 60** — includes `/_clock/set_current_utc` (default 2026-08-01T00:00:00Z), computed reads (exposure, success-rate analytics), dual offset-allocation paths (waterfall + manual)
- **Errors: 29**, **roles: 10** (incl. `entity_backed:Payer` PayerAgent with ownership checks, segregation-of-duties on CAP verify), **concurrency rules: 2** (OCC on records amendment and demand adjustment — both pass the serial-observability filter)
- **Difficulty instances: 23** across all nine rules (dual-variant 2, combinatorial 3 covering modes a/b/c, non-linear SM 3, cascades 2 at depths 5 and 3, priority conflicts 3 with distinct category pairs, boundary 3 across time/cents/set-cardinality metrics, cross-entity deps 3, temporal overlap 2 with half-open vs capacity semantics, invariants 2 over distinct conserved quantities). All formula-derived asserts pre-computed (e.g., net 363640 vs gross 400000; per-demand rounded interest 333+333=666; tiered interest 40000 vs hold-adjusted 20000).
- **Corner instances: 67** (55 active recipes + 12 `excluded_because` stubs citing difficulty instances), spanning all nine claim-guide sections.

### Verification

- `scaffold_lint.py`: **VERDICT: clean lint** (806 calls scanned across §1.8+§1.9, all FKs reverse-reachable).
- Additional scripted checks: zero unbound `${var}` placeholders, instance names unique across both design files, all `grounds:` resolve to declared §1.1–§1.7 elements, no forbidden concurrency vocabulary.
- Two issues found and fixed during authoring: YAML 1.1 boolean coercion of the capture key `off` (quoted), and lint check (f)'s literal `{id}` path-param requirement for sub-resource matching (renamed all parent path params to `{id}`).

## Step 3: Copy shared files — 2026-08-14T14:30:39.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1754_payer_audit_appeal_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T14:57:45.000Z

Done. The PRD is written and all three hard contracts pass.

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/workspace/PRD.md` — 372 lines.

**Section list:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (all 10 roles with identity translations; PayerAgent entity-backed vs. 7 opaque roles), 2.2 API Response Structure (byte-identical verbatim block, verified by containment check), 2.3 Pagination, 2.4 Logical Clock (default `2026-08-01T00:00:00Z`, sweep semantics, lazy appeal expiry), 2.5 Common Resource Properties (incl. AuditCaseEvent lacking `updated_at`/`version`), 2.6 Monetary Precision (integer cents, round-half-up, pinned rounding orders), 2.7 OCC (both rules: `expected_audit_case_version` on records-submissions, `expected_recoupment_demand_version` on adjustments → `ERR_STALE_VERSION` 412), 2.8 Inclusive Deadline Semantics, 2.9 Validation Order (all 11 priority tiers as an explicit ordered list), 2.10 Nested Retrieval (left-to-right, `id`/`itemId`), 2.11 Append-Only Event Trail
- §3 Business Logic (9 subsections, chronological-workflow grouping): 3.1 Payer Config & Issue Taxonomy, 3.2 Intake & Records Deadline, 3.3 Review & Determination, 3.4 Appeal Ladder, 3.5 Decisions & Finalization, 3.6 Evidence Packets, 3.7 Recoupment & Interest, 3.8 Remittances & Waterfall, 3.9 Analytics/Closure/CAP
- §4 Endpoint Definitions: 60-row table, 4 columns only (Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue: 29-row table, 2 columns only

**Coverage-audit notes (mechanical, script-verified):**
- Contract 1 (field names): 115/115 required identifiers present as standalone backticked tokens (entity fields, endpoint inputs, query params, path params incl. `itemId`, common fields, computed-read outputs like `current_utc`, `gross_dollars_at_risk_cents`, `net_exposure_cents`, `snapshot_quarter_start`, `rows`). Two gaps found in the first pass (`itemId`, `EFFECTIVENESS_CHECK` standalone) were repaired and re-verified.
- Contract 2 (rule coverage — manual walk): all 11 state machines' transitions with preconditions and side effects expressed; both OCC rules with endpoint + field + error + status and no race framing; all 9 calculations (records deadline, appeal deadlines per level/track, GROSS/NET exposure with frozen prior-quarter snapshot and 5000-bp default, SIMPLE/DOLLAR_WEIGHTED success rates, tiered interest accrual with 30-day periods and cap, waterfall with per-demand rounding pin incl. the 333+333=666 illustration, case totals with conservation invariant, half-open overlap with adjacency exemption, vacuous-truth packet readiness, concurrent-cap boundary) rendered in reconstructible prose; all cross-entity cascades (auto-denial, full-vindication reversal, hold acquire/release, offset reversal) stated; validation priority ordering explicit in §2.9; all 29 error IDs appear in §2/§3 prose with their trigger conditions.
- Contract 3 (§3 path purity): 621 backticked tokens scanned in §3, zero path/method/combo violations.
- Document ends at §5 with no audit footer; no example-task error IDs leaked; constants embedded in business units ($25,000 director threshold, 14-day CAP window, 3-cycle cap, 50% default overturn rate).

The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

## Step 5: Generate unit tests — 2026-08-14T15:40:00.000Z

Complete. Final audit passes with full coverage of both design indices.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/`):

`test_helpers/` (9 files):
- `types.py` — 12 entity TypedDicts (AuditCaseEvent correctly omits `updated_at`/`version` per its append-only `common_fields: false`), 17 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~45 endpoints)
- `api_errors.py` — all 29 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_case_conservation` (billed == upheld + denied_active + final_denied)
- `factories.py` — payload factories incl. determination outcome builders (denied/paid/partial)
- `constants.py` — logical-clock default, director threshold, CAP window/cycles, default overturn bp, 30-day interest period
- `test_users.py` — 8 role header constants + per-instance builders; `make_payer_agent_headers(payer_id)` for the entity-backed PayerAgent role
- `fixtures.py` — composite chains: `setup_determined_case`, `reach_draft_appeal` (level walker), `setup_level3_appeal`, `setup_case_with_demand`, CAP state builders, and named scenarios (exposure divergence with prior-quarter history, waterfall rounding pair, tiered-interest hold pair, hold cycle, full-reversal cascade, missed deadline, cross-payer offset, hold-follows two-payer, overlap)
- `__init__.py` — barrel export

`test_suite/` — `conftest.py` + 10 domain test files (payer/issue config, auth & validation priority, intake & records, determination & closure, appeal ladder, evidence packets, recoupment & interest, remittances & cascades, exposure analytics, corrective action plans).

**Test counts**: 97 tests total — queue A (Difficulty): 44 tests covering 22 instances (≥2 each); queue B (Corner): 53 tests covering all 53 non-stub instances (1 each). All 12 `excluded_because:` stubs left untranslated; each test's docstring ends with exactly one verbatim `Design:` tag and a verbatim PRD citation (148/148 citation fragments grep-verified against PRD.md). Pytest collection clean; pyflakes clean.

**Skipped instances** (PRD-first filter, gaps left as gaps):
1. `Difficulty/dual_variant_calc/success_rate_simple_vs_dollar_weighted` — the PRD describes success-rate `rows` only as "rows grouped by payer and issue code"; the asserted row fields (`success_rate_bp`, `decided_count`, `favorable_count`, `partial_count`, `unfavorable_count`) appear nowhere in PRD prose, so a PRD-only implementer could ship different row key names.
2. `Corner/calculations/success_rate_excludes_withdrawn_and_expired` — same row-schema gap (needs `decided_count`/`success_rate_bp`).
3. `Corner/calculations/analytics_window_half_open_bounds` — same gap (window inclusion is only observable through `decided_count`).

(The related error-path instance `Corner/validations/analytics_window_inverted_rejected` *is* covered, since `ERR_ANALYTICS_WINDOW_INVALID` is PRD-named.)

**Note**: the corner stub `Corner/errors/err_stale_version_covered` cites `difficulty_instance: occ_records_submission_stale_version`, which lives in the corner file's own cross_cutting section, not the difficulty index — matching the stub's rationale text, so it resolves and both OCC corner instances were translated.

## Step 6: Generate implementation — 2026-08-14T15:40:00.000Z

All smoke tests pass on a fresh `start.sh` boot (exit 144 is just the `pkill` on our own shell's process group at the end — the smoke run printed PASSED before it). The implementation is complete.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/workspace/implementation/`):
- `app.py` — the entire Flask implementation (~2100 lines, single module)
- `start.sh` — executable launcher; guards the pip install behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `0.0.0.0:$PORT` default 10000)
- `requirements.txt` — `flask>=3.0`

**Endpoint count: 60/60** routes from the SCAFFOLD §1.5 endpoint table implemented and verified by cross-checking the Flask route registry against the scaffold list.

**Storage:** pure in-memory module-level `db` dict keyed by id (12 entity stores). No disk, no SQLite, no seeding at startup — verified empirically that re-invoking `start.sh` yields `total_count: 0` on a fresh boot.

**Notable design decisions:**
- **Logical clock** at module scope, defaulting to `2026-08-01T00:00:00Z`; `POST /_clock/set_current_utc` runs the missed-deadline auto-denial sweep and claim-line finalization sweep. Appeal expiry is lazy (only on file attempt), per PRD.
- **Chronological ordering:** since the logical clock is frozen between clock-sets, all entities get a monotonic `_seq` counter; list sorting and event trails use it (internal field, stripped from serialized views). This fixes event-trail chronological order when many events share one timestamp.
- **Integer-only money math:** `round_half_up` implemented on integer numerator/denominator pairs (no `Decimal`, no floats); interest cap comparison done in scaled-integer space to preserve exact round-half-up-after-min semantics. Verified the pinned per-demand waterfall rounding example (333+333=666) and tier1/tier2/cap boundaries.
- **Full-vindication cascade:** appeal decisions recompute case totals, then release ON_HOLD demands and reverse all live demands + their APPLIED offsets + remittance credits when `total_denied_active_cents` hits 0 — including the FULLY_RECOUPED → REVERSED refund path.
- **Validation priority order** follows PRD §2.9: auth → role → body → analytics-window → existence (left-to-right) → PayerAgent ownership → state (incl. domain-specialized state errors) → SoD/director → temporal → uniqueness/track/determination → cross-payer → money ceilings; OCC checked after state guard on the two OCC-guarded endpoints.
- **Derived fields** recomputed on read: `accrued_interest_cents`, `outstanding_principal_cents`, `available_cents`, remittance status; interest rate snapshots captured at demand creation.
- **`principal_at_issue_cents`** stored at creation (separate from mutable `principal_cents`) so the interest cap uses the at-issue principal per PRD §3.7.

**Verification:** four smoke suites (60+ assertions) covering CRUD, RBAC/auth errors, OCC 412s, missed-deadline sweep + late-submission revert, determination content checks (422s), appeal ladder through LEVEL_3 with evidence-packet gating, holds/waterfall/reversal, interest tiers + cap + rounding, director close threshold (403), CAP segregation-of-duties and window checks, analytics variants + window validation, pagination meta, and the append-only event trail — all pass on a fresh `start.sh` boot.

## Step 7: Test/fix iteration loop — 2026-08-14T15:55:00.000Z

**All 8 rounds: 97/97 passed, 0 failed.** Clean 8-round sweep achieved.

**Iterations run**: 2 sweeps (initial baseline + post-fix verification). One implementation fix; zero test deletions; zero test_helper changes.

**Tests deleted**: None.

**Fixes applied to `test_helpers/`**: None.

**Fixes applied to `implementation/`**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/workspace/implementation/app.py`, function `fmt_dt` — was always rendering three fractional digits (`...T00:00:00.000Z`); now drops the fractional part when microseconds are zero, so rendered timestamps match the PRD's only directly-quoted timestamp format (`2026-08-01T00:00:00Z` in §2.4) and the input format used by every fixture. This one change resolved all six previously-failing tests, which were asserting exact string equality on computed timestamps (`records_due_at`, `determination_issued_at`, `filed_deadline_at`, `snapshot_quarter_start`) without fractional digits.

**Failure analysis**: All 6 baseline failures were the same root cause — implementation produced `2026-08-31T00:00:00.000Z`, tests expected `2026-08-31T00:00:00Z`. PRD §2.5 mandates "three fractional digits" only for `created_at`/`updated_at`; the PRD's only direct timestamp example (`2026-08-01T00:00:00Z` for the logical-clock start) carries no fractional digits, and every input fixture passes timestamps without them. Making `fmt_dt` emit `Z` when `microsecond == 0` and `.NNNZ` otherwise honors the PRD's three-fractional-digit requirement whenever real sub-second precision exists while aligning with the PRD's own example for the (universally used) whole-second case. The assertions on `created_at`/`updated_at` in `test_helpers/assertions.py` go through `is_iso8601_timestamp`, which accepts both forms, so the change is safe across the board.

**Final state**: 8/8 rounds passed at 97/97, zero failures. Done.

## Step 8: Finalize PRD — 2026-08-14T16:05:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/workspace/PRD_FINALIZED.md` with three surgical edits, all tracing to the single Step 7 item (the `fmt_dt` fractional-seconds fix).

### Line counts and delta

- `PRD.md`: 372 lines; `PRD_FINALIZED.md`: 374 lines (+2 lines, +0.54%). Two lines revised in place, one two-line paragraph inserted.

### Changes

- §2.2 (Standard Success Response Format) — revise — the `api_request_timestamp` bullet now states the timestamp carries three fractional digits when sub-second precision is present and none at whole-second instants, cross-referencing §2.5 — `implementation/app.py:142-146` (`_meta`), `app.py:65-75` (`fmt_dt`).
- §2.5 (Common Resource Properties) — insert — new closing paragraph pinning the universal timestamp-rendering rule: ISO 8601 UTC with `Z` suffix, exactly three fractional digits when sub-second precision exists, fractional part omitted at exact whole seconds; explicitly covers `created_at`/`updated_at`, `api_request_timestamp`, deadline/status timestamps (`records_due_at`, `determination_issued_at`, `filed_deadline_at`, `snapshot_quarter_start`), client-derived timestamps (`received_at`), and `current_utc` — `implementation/app.py:65-75` (`fmt_dt`), callsites at `app.py:117,127,145,536,542,576,718,870,873,948-949,1015,1022,1124,1211,1243,1336,1401,1408,1457,1623,1651,1780,1868,1912,1995`.
- §2.5 — revise — the `created_at` bullet drops the absolute "with three fractional digits" claim and defers to the new rendering rule — `implementation/app.py:116-123` (`stamp_new`).

### Per-edit pre-edit search log

**Edit 1 (§2.2 `api_request_timestamp` bullet)**
- (a) Subject: rendering format of `api_request_timestamp` in response envelopes.
- (b) Paths enumerated: `_meta()` at `app.py:142-146` (sole producer, used by both success and error envelopes via `ok_object`/`ok_list`/`error_response` at lines 149-164 and 2115); `_meta` delegates to `fmt_dt(datetime.now(timezone.utc))` — the wall clock, which essentially always has non-zero microseconds, so the `.NNNZ` branch dominates here, but whole-second rendering is still possible and correct. Verified no other code path writes `api_request_timestamp`. Also verified the PRD's error-envelope example shares the same bullet-free format, so no second prose site needed editing.
- (c) Wording adjustment: none needed beyond the planned softening; the sentence says "when sub-second precision is present," which exactly matches `fmt_dt`'s `if millis:` branch for this path.

**Edit 2 (§2.5 rendering-rule paragraph)**
- (a) Subject: rendering format of every server-emitted timestamp.
- (b) Paths enumerated: full grep of `fmt_dt` (27 callsites listed above) covering `stamp_new`/`touch` (all `created_at`/`updated_at`), `_meta` (`api_request_timestamp`), audit intake (`received_at` echo + `records_due_at` computation at 870-873), claim-line service dates (948-949), records submissions (1015, 1022), determination (1124), analytics `snapshot_quarter_start` (1211), case close (1243), appeal `filed_deadline_at`/`filed_at` (1336, 1401), hold/decision timestamps (1408, 1457), packet `submitted_at` (1623), demand `issued_at` (1651), offset `applied_at`/`reversed_at` (1780, 1868, 1912), CAP `check_started_at` (1995), and the admin clock `current_utc` (718). Also enumerated the parsing side: `parse_dt`/`req_dt` (lines 52-63, 250-263) — client-supplied values like `received_at` and `to_iso8601` are parsed to datetimes and re-rendered through `fmt_dt`, so a fixture input of `2026-08-01T00:00:00Z` round-trips without fractional digits (deadline computations add whole days, staying on whole seconds — confirmed at 873 and 1330-1336). Also checked `test_helpers/assertions.py`: all timestamp checks go through `is_iso8601_timestamp`, which accepts both forms, so no hidden dependency on either branch.
- (c) Wording adjustment: the enumeration was deliberately written as an open list ("such as") rather than a closed one, and the rule is stated once globally instead of per-field, so no enumerated path is mis-described and unlisted fields (e.g. `occurred_at`, `submitted_at`, `decided_at`, `closed_at`, `applied_at`, `reversed_at`, `check_started_at`, service dates) are covered by the leading universal quantifier without being named.

**Edit 3 (§2.5 `created_at` bullet)**
- (a) Subject: format claim attached specifically to `created_at` (and, by proximity, `updated_at`).
- (b) Paths enumerated: `stamp_new` (116-123) and `touch` (126-128) — the only writers of `created_at`/`updated_at` — both go through `fmt_dt(clock_now())`; the logical clock starts at a whole second (`_clock` init at line 44, `2026-08-01T00:00:00Z`) and `advance_clock` sets it from `req_dt` input (715-718), which in every fixture is whole-second. Hence the common case renders without fractional digits, and the old absolute "with three fractional digits" claim mis-described it. The `AuditCaseEvent` exception sentence (append-only, `created_at` only) was checked and remains accurate — event `created_at`/`occurred_at` also flow through `fmt_dt` (536, 542), which the new global paragraph already covers.
- (c) Wording adjustment: rather than repeating the whole rule inside the bullet, the bullet defers to "the timestamp-rendering rule at the end of this section," keeping the bullet short and guaranteeing the two sentences cannot drift apart.

## Step 9: Complete PRD — 2026-08-14T16:25:00.000Z

All 23 logical changes applied cleanly across 21 diff hunks. Final verification is done.

**Source vs output:** `PRD_FINALIZED.md` (374 lines, 63,103 chars) → `PRD_COMPLETED.md` (375 lines, 67,027 chars); char-delta **+3,924**, 21 diff hunks (20 in-place line revisions + 1 inserted line).

**Counts:** ambiguity-pins **20**; mismatch-revisions **3**.

**Changes** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/workspace/PRD_COMPLETED.md`; impl refs are `/home/ubuntu/github/CodingPRD/tasks/task_1754_payer_audit_appeal_management/workspace/implementation/app.py`):

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` rejected with `ERR_INVALID_REQUEST` (400) — app.py:268-283
- §2.3 — revise — **mismatch** — list ordering pinned as creation (insertion) order, `created_at`-ascending with creation sequence as tie-break, not literal `created_at` value order (impl sorts by `_seq`, app.py:286-289)
- §2.4 — insert — ambiguity — envelope `api_request_timestamp` is rendered from the host wall clock, not the logical clock — app.py:142-146
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — app.py:116-123
- §2.9 — insert — ambiguity — OCC expected-version check (`ERR_STALE_VERSION` 412) placed at new tier 6.5, after state guards, before segregation/temporal — app.py:1003-1007, 1709-1713
- §2.9 — insert — ambiguity — packet-item attach validates its body (`document_ref`) before the header tier — app.py:1575-1580
- §3.2 — insert — ambiguity — claim lines may be added in any case status except `CLOSED` (→ `ERR_INVALID_STATE_TRANSITION`) — app.py:926-927
- §3.2 — revise — ambiguity — late submission moves the case `MISSED_DEADLINE → RECORDS_SUBMITTED` (was unstated) — app.py:1021
- §3.2 — insert — ambiguity — missed-deadline sweep advances case `version` by two (status write + totals write); each auto-denied line +1 — app.py:601-620
- §3.3 — revise — ambiguity — determination `issue_code_id` is optional/nullable on denial outcomes — app.py:1103-1105, 1122
- §3.3 — revise — ambiguity — content checks run belonging → coverage → amounts, entries in request order; per-entry field validation (outcome/category/denied type/`issue_code_id` resolution) happens with the amounts step, after belonging/coverage — app.py:1071-1111
- §3.4 — insert — ambiguity — opening an appeal on an auto-denied line of a `MISSED_DEADLINE` case (no `determination_issued_at`) fails with `ERR_INVALID_REQUEST` (400) — app.py:1309, 700-704
- §3.5 — insert — ambiguity — finalization at track maximum consults the last decided appeal's own `filed_deadline_at`; auto-denied lines (no determination) are never finalized — app.py:634-642, 650-659
- §3.6 — revise — ambiguity — packet creation allowed for an appeal at any level and in any appeal status — app.py:1496-1510
- §3.6 — insert — ambiguity — an empty packet is created already at `version` 2 (creation + immediate readiness flip) — app.py:1503-1509
- §3.7 — insert — ambiguity — demand records `principal_at_issue_cents` (the cap-anchoring field, present in responses) — app.py:1650
- §3.7 — revise — **mismatch** — adjustment no longer claimed to "never change the demand's status": status is recomputed post-adjustment, so lowering principal to exactly the consumed amount lands the demand in `FULLY_RECOUPED` — app.py:1723-1725
- §3.8 — insert — ambiguity — waterfall candidate ordering gains creation sequence as the final tie-break — app.py:1847
- §3.8 — insert — ambiguity — reversing an offset on an `ON_HOLD` demand leaves the demand `ON_HOLD` — app.py:509-512, 1914-1916
- §3.9 — insert — ambiguity — `snapshot_quarter_start` pinned as the first instant of the prior completed calendar quarter — app.py:1137-1149, 1211
- §3.9 — insert — ambiguity — success-rate analytics envelope pinned as `response_type` `object` with `data.rows`; row schema pinned as `payer_id`, `issue_code_id` (nullable), `decided_count`, `favorable_count`, `partial_count`, `unfavorable_count`, `success_rate_bp`, `variant`; row ordering `payer_id` then `issue_code_id` (null group first); `limit`/`offset` apply; invalid `variant` or unparseable `from`/`to` → `ERR_INVALID_REQUEST` (400) — app.py:2039-2121
- §3.9 — insert — ambiguity — marking a plan ineffective is subject to neither the segregation-of-duties check nor the 14-day window guard — app.py:2020-2033
- §4 — revise — **mismatch** — waive endpoint table cell corrected from "pending required item" to "pending item" (impl waives any `PENDING` item) — app.py:1590-1598

**Notes:** No new sections or paragraphs were added — all changes are inline sentence inserts/revisions (the single added line is the §2.9 tier-6.5 list item). Everything else in the impl (endpoint roster, role sets, error catalogue, interest formula, rounding order, cascade effects, event types/ordering, deadline inclusivity) was verified as already uniquely pinned by the PRD.
