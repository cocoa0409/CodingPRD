# Worklog — task_1859_physician_call_schedule_locum_coverage

Scenario: Physician Call Schedule & Locum Coverage (hospital medical staff scheduling) — call rotation generation with fairness & equity rules, holiday/weekend distribution & swap marketplace, coverage gap detection & locum requisition, locum credentialing & onboarding timeline, call pay/stipend accounting & moonlighting rules, unavailability (vacation/CME) constraints, backup call activation, hospital coverage requirement compliance.

## Step 1: Create Task Directory — 2026-08-14T21:18:00.000Z

Directory `tasks/task_1859_physician_call_schedule_locum_coverage/` and `workspace/` were pre-created by the pipeline launcher (per skill invocation args); verified present with INSTRUCTION.md and all required skills available.

## Step 2: Generate Scaffold — 2026-08-14T22:10:00.000Z

Scaffold generation complete for task 1859. All three artifacts are written and pass clean lint plus mechanical consistency checks.

**Files** (under `/home/ubuntu/github/CodingPRD/tasks/task_1859_physician_call_schedule_locum_coverage/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts**
- 10 entities: CallProgram, Physician, UnavailabilityWindow, CallSlot, CallAssignment, SwapRequest, CoverageGap, LocumRequisition, CredentialingCase, PayEntry
- 10 state machines (3 cyclic: SwapRequest POSTED⇄CLAIMED, LocumRequisition OPEN⇄CREDENTIALING, CallSlot OPEN⇄ASSIGNED; plus CoverageGap OPEN⇄REQUISITIONED)
- 7 calculations (slot generation, fairness-weighted auto-assign selector, dual-variant fairness points, rolling 28-day moonlight hours, dual-variant call pay, payroll totals with pinned rounding order, coverage compliance)
- 11 validation priority rows; 50 endpoints; 60 error codes; 4 roles (SchedulerAdmin/ChiefOfStaff/CredentialingOfficer opaque, Physician entity-backed)
- 1 OCC concurrency rule (regenerate guarded by `expected_call_program_version`, 412)
- Difficulty design: 18 instances (2 per rule × 9 rules), all non-stub
- Corner design: 85 instances — 74 with full recipes, 11 `excluded_because` stubs pointing at difficulty instances

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint` — 712 calls scanned across §1.8+§1.9, all conform to §1.5; all FKs reverse-reachable
- No instance-name duplicates; every `grounds` reference resolves; every error code is exercised beyond its catalog entry; no forbidden concurrency vocabulary; all numeric asserts pre-computed (e.g., 74175 = 21500×1.5×2.0×1.15; payroll rounding 3×30906=192718 vs forbidden 192719)

**Notable design decisions**
- Archetype: temporal-windowing primary + quota/allocation secondary; **flat topology** (`/api` prefix, FK joins, no nested URLs) and **cyclic** state shape — both diversity-prioritized per §0.3
- Fairness lives on a computed report + generation selector (no RosterEntry entity) to keep 10 dense entities; point ownership transfers via status-set filtering (SWAPPED excluded), which is what makes the swap points-conservation invariant clean
- Two overlap rules with deliberately different interval semantics: unavailability windows are closed date intervals (touching dates conflict) vs assignment call windows half-open `[07:00, +24h)` (adjacency allowed)
- Credentialing auto-fill cascade is the depth-5 transitive chain (complete-item → case CLEARED → requisition READY→FILLED → assignment created → slot ASSIGNED/gap RESOLVED); window approval is the depth-2 counterpart
- Logical clock test-driving endpoint with the mandated `2026-08-01T00:00:00Z` startup default; all fixture dates (Sept 2026, incl. Labor Day 2026-09-07 as the holiday-on-Monday) verified programmatically
- Endpoint count (50) exceeds the Expert guideline band — driven by 10-entity flat-topology FK reverse-reachability reads; interaction density prioritized over surface size per §0.4's density-over-volume guidance

## Step 3: Copy Shared Files — 2026-08-14T22:12:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1859_physician_call_schedule_locum_coverage/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T22:30:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1859_physician_call_schedule_locum_coverage/workspace/PRD.md`.

**Output**: `PRD.md` — 331 lines, generated from `SCAFFOLD.yaml` only (the two difficulty/corner index files were not opened).

**Section structure**
- §1 Introduction — 2 paragraphs, business-context angle (after-hours coverage obligation → full-lifecycle system description)
- §2 Global Specifications — 11 subsections: 2.1 RBAC (all 4 roles with identity prose: `Physician` entity-backed, the other three opaque), 2.2 Response Structure (verbatim, verified byte-identical), 2.3 Pagination, 2.4 Common Resource Properties (all 10 entities share `id`/`created_at`/`updated_at`/`version`), 2.5 Logical Clock (startup default `2026-08-01T00:00:00Z`, never wall-clock), 2.6 Call Windows & Calendar Classification (07:00→07:00 half-open windows, `call_hours` 24, HOLIDAY > WEEKEND precedence, closed-vs-half-open interval semantics), 2.7 Payroll Ledgers & Precision (per-entry rounding pinned, budget gate), 2.8 Fairness Points & Equity Band (per-slot rounding pinned), 2.9 Moonlighting & 28-day Rolling Windows (projected vs served-only variants), 2.10 OCC (regenerate only), 2.11 Validation Order (all 11 priorities as an ordered list)
- §3 Business Logic — 6 subsections by workflow stage: 3.1 program setup/generation/publication, 3.2 physicians & unavailability windows, 3.3 assignments/activation/serving, 3.4 swap marketplace, 3.5 gaps & locum pipeline, 3.6 payroll/reporting/reconciliation
- §4 Endpoint table — 50 rows, 4 columns (Method, Path, Description, Authorized Roles)
- §5 Error catalogue — 60 rows, 2 columns, no trigger conditions

**Coverage-audit results (all three hard contracts PASS)**
- Contract 1 field-name coverage: 95 required identifiers (entity fields + endpoint inputs/query params + report/clock output fields + checklist item names) — 95 present, 0 missing
- Contract 2 rule coverage: every state-machine transition (10 machines, including all sibling branches: window cancel from REQUESTED/APPROVED, requisition cancel from OPEN/SOURCED/CREDENTIALING, case fail/expire from INITIATED/IN_PROGRESS, swap cascade-cancel from POSTED/CLAIMED/APPROVED), all 7 calculations with exact formulas in reconstructible prose, all 11 validation priorities with ordered prose, the 1 OCC rule (`expected_call_program_version` → `ERR_STALE_VERSION` 412), all 60 error IDs mentioned in §2/§3 prose, all field defaults/structured content stated, fiscal gate's three `applies_to` scopes enumerated
- Contract 3 §3 path purity: 279 backticked tokens scanned, 0 paths / 0 bare HTTP methods / 0 method+path tokens

**Notable scattering/narrative decisions**
- Program creation's 26 config fields are deliberately split: core calendar/count fields in §3.1, rates/multipliers in §3.3 (serve-time pay), point weights in §2.8, moonlight knobs in §2.9, `swap_cutoff_hours` in §3.4, `credentialing_lead_hours` in §3.5 — so the creation payload must be reassembled across five subsections.
- Constants rendered with unit flavor: 120-hour credentialing lead as "five days", 50,000/20,000-cent rates, 48-hour cutoff, 96-hour cap — no pseudocode, no fuzzy words (verified by scan), all equality/strictness boundaries stated explicitly ("exactly at the cutoff is allowed", "strictly greater", "an exact fit is permitted").
- The credentialing auto-fill chain is narrated as a 5-hop cascade (item → case CLEARED → requisition READY→FILLED with READY transient → assignment LOCUM_FILL → slot ASSIGNED + gap RESOLVED + reserve update under the fiscal gate), and the gap-state asymmetry (fail/expire re-opens the requisition but the gap stays REQUISITIONED) is called out explicitly.
- §2.11 expresses the full priority ladder as a numbered list so "four independent checks" ambiguity cannot arise; body-id ordering (`slot_id` before `physician_id`) appears both there and in §3.3.

## Step 5: Generate Unit Tests — 2026-08-14T22:48:00.000Z

Both stages are complete and fully audited. Summary:

## Totals

**111 tests emitted, 0 instances skipped.**
- **Queue A (Difficulty):** 36 tests — all 18 instances with exactly 2 tests each.
- **Queue B (Corner):** 75 tests — all 74 non-stub instances with ≥1 test (`rolling_window_28day_inclusion_boundary` got 2, splitting the D-28-excluded and D-27-included assertions).
- **11 `excluded_because:` stubs** not translated; every cross-reference verified to resolve to a real §1.8 difficulty instance.

**Skipped instances:** none. The PRD verbatim-covers every asserted rule with unique derivability — §2.11 pins the validation precedence used by both priority-pair instances, §2.7/§2.8/§2.9 pin rounding order, variant semantics, and equality boundaries, and every asserted `error_id` has a PRD-prose trigger condition. The closest call was `create_physician_system_fields_input_ignored` (retained: PRD §2.4's "server-minted UUID" / "version starts at 1" pins the outcome, and §2.11's shape-check enumeration does not license rejecting extra fields).

## test_helpers/ inventory (under `/home/ubuntu/github/CodingPRD/tasks/task_1859_physician_call_schedule_locum_coverage/test_helpers/`)

- `types.py` — 19 enums + 10 entity TypedDicts (all ten resources carry id/created_at/updated_at/version per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 50, `/api` prefix)
- `api_errors.py` — `ApiErrorId` (61 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + payroll-ledger invariant checker
- `factories.py`, `constants.py` (clock default, rates, multipliers, thresholds, checklist order), `test_users.py` (shared constants for opaque roles + `make_physician_headers` for the entity-backed Physician role)
- `fixtures.py` — composite tiers: program lifecycle (`create_draft/generated/published_program`), `setup_published_with_assignment`, swap chain (`setup_posted/claimed/approved_swap`), locum chain (`setup_shortfall_program` → `setup_open_requisition` → `setup_sourced_requisition` → `setup_credentialing_case` → `setup_filled_requisition`), window helpers, slot/gap lookup via the pinned sort order
- `__init__.py` barrel export

## Notable fixture decisions

1. **Physician registration timing is load-bearing**: fixtures register physicians *after* generation when the recipe needs OPEN slots + GENERATION_SHORTFALL gaps (manual backfill path), and *before* generation when it needs GENERATED-origin auto-assignment (tiebreak, empty-pool, regenerate-with-progress).
2. **Logical clock discipline**: setups rely on the 2026-08-01T00:00:00Z startup default (before every 48h swap cutoff and 120h credentialing `clear_by`), advancing explicitly only where the recipe requires it (activation windows, serves, reconcile, OCC).
3. **Fairness-report entries**: PRD pins the report's top-level fields but not entry key names, so entries are located by physician-id value membership and point values asserted by numeric-value membership (`fairness_entry_for`/`numeric_values`) — satisfying the two-reader rule without weakening the 3.0/1.0/5.0 assertions.
4. **Identity threading**: all ownership-gated calls (swap offer/claim, window create/cancel, physician-side backup activation) use `make_physician_headers(entity["id"])`, never the shared fallback.

## Audits run (all clean)

- Tag audit: every test has exactly one `Design:` line resolving to a real instance; no orphan tags; difficulty instances ≥2, corner non-stubs ≥1.
- Citation audit: all 111 docstrings carry a verbatim ≥8-word PRD substring confirmed by normalized grep against `workspace/PRD.md`.
- `compileall` + `pytest --collect-only`: 111 tests collected, no import errors; no skip/xfail markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T23:06:00.000Z

Implementation complete; first full run scored 110/111 (the one failure was self-swap ordering — fixed and verified live); both end-to-end smoke suites pass against the fixed code. (The subagent's self-armed monitor on a third suite run was in its own session and lapsed on exit; Step 7's 8-round sweep is the authoritative verification.)

File inventory: `start.sh` (executable, $PORT/0.0.0.0/foreground), `requirements.txt`, `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validation.py`, `routes/` (3 entries incl. subdir), `services/` (3 entries incl. subdir).

## Step 7: Iterate Tests + Fixes (8-round parallel stability sweep) — 2026-08-14T23:20:00.000Z

Sweep 1 (baseline): 7/8 rounds clean at 111/111; round 6 flaked on
`test_07_moonlight_overlap_and_budget.py::test_rolling_window_includes_call_at_d_minus_27`
with `requests.exceptions.ConnectionError: Connection reset by peer` at 1.372s —
a transport-level failure, not an assertion failure.

Diagnosis: per-test-server isolation SIGKILLs and respawns the API server on the
same port before every test, while the task's module-level `api_client` pooled
keep-alive connections on a shared `requests.Session` (werkzeug dev server runs
HTTP/1.1 keep-alive). A pooled connection to the just-killed server incarnation
raced the next request and surfaced as RST. Classic stale-pool-across-restart
flake (1 failure in 888 test executions).

Fix (test_helpers only, no assertion touched): `test_helpers/api_client.py` —
`ApiClient._request` now merges `Connection: close` into every request so urllib3
never reuses a pooled connection across a server restart; each request opens a
fresh socket to the current server.

Sweep 2 (verification): all 8 parallel rounds clean, 111/111 each (888/888).
No tests deleted; no test_suite or implementation changes required.

## Step 8: Finalize PRD — 2026-08-14T23:35:00.000Z

Done. `PRD_FINALIZED.md` is written and verified byte-identical to `PRD.md`.

**Line counts / delta:** PRD.md = 330 lines, PRD_FINALIZED.md = 330 lines, 0% delta (verified with `cmp`: byte-identical).

**Changes made:** none.

### Why no edits — diligence performed

The sole `<step_7_diff>` item is a client-side transport fix in `test_helpers/api_client.py` (`ApiClient._request` now merges `Connection: close` into every request) to cure a stale-pooled-connection race against the per-test-server SIGKILL/respawn harness. Evaluated as a candidate PRD edit and rejected:

**(a) Subject identified:** HTTP transport connection reuse — whether the PRD must pin server behavior around keep-alive / connection lifetime that the test client's fix implies.

**(b) Impl paths enumerated and read/grepped (all of them, not just the Step 7 site):**
- `implementation/app.py` (full file read) — server bootstrap is stock Flask: `app.run(host="0.0.0.0", port=port, threaded=True)` (lines 56-58); no connection management, no keep-alive configuration, no socket/session handling anywhere.
- Full-implementation grep for `keep-alive|connection|socket|session|pool` across all `.py`/`.sh` — the only hits are `_eligible_pool` in `services/domain.py` (physician eligibility pool, unrelated domain logic). Zero transport-layer code exists in the server.
- `implementation/middleware.py` — the only header handling in the entire implementation is the application-level auth headers `X-User-ID`/`X-User-Role`, which PRD.md already specifies verbatim (§2.1 line 15, §2.11 line 122, §5 line 271).
- PRD.md grep for `keep-alive|connection|header|HTTP/1|transport|socket|werkzeug|flask` — the PRD's only header language is the auth-context headers above; it is silent on transport, which is correct since INSTRUCTION.md leaves language/framework open.
- The flaked test `test_07_moonlight_overlap_and_budget.py::test_rolling_window_includes_call_at_d_minus_27` (read) — its assertion (`ERR_MOONLIGHT_CAP_EXCEEDED`, 409, rolling 28-day window boundary) was untouched by Step 7; the failure was `requests.exceptions.ConnectionError`, a transport reset, passing 7/8 pre-fix and 8/8 post-fix.
- File mtimes confirm all `implementation/` sources predate the Step 7 sweep (last source touch 23:06; sweep at 23:20); only runner `results.N.json` outputs are newer. Step 7 changed zero implementation and zero test_suite files.

**(c) Wording adjustment:** none — no edit committed.

**Conclusion:** The fix pins behavior of the *test client*, not the server. The implementation exhibits no designed connection-management choice (stock werkzeug defaults), and any HTTP/1.1 server interoperates identically with a `Connection: close` client — so there is no implementation behavior here that PRD.md fails to uniquely determine. Adding wording (e.g., mandating keep-alive support or connection closure) would invent a constraint the implementation does not exhibit and would itself become a new PRD/impl mismatch. Per the "do not invent edits" instruction, the correct output is a byte-identical copy.

## Step 9: Complete PRD — 2026-08-14T23:55:00.000Z

All edits are in place and verified. Final report:

**File:** `workspace/PRD_COMPLETED.md`
**Source:** `PRD_FINALIZED.md` (existed; identical to `PRD.md`)
**Size:** 330 → 335 lines; 50,729 → 54,524 chars (**+3,795 chars**)
**Counts:** 19 ambiguity-pins, 6 mismatch-revisions (25 edit sites)

### Ambiguity-pins (PRD silent → inserted what impl does)

- §2.2 — insert — ambiguity — unmatched route/verb → `ERR_NOT_FOUND` 404, unexpected exception → `ERR_INVALID_REQUEST` 400 — `app.py:36-48`
- §5 — insert — ambiguity — added `ERR_NOT_FOUND | 404` catalogue row — `app.py:36-42`
- §2.3 — insert — ambiguity — limit/offset out-of-range clamped (not rejected), non-integer falls back to defaults, `has_more` = offset+returned < total_count — `response.py:73-105`
- §2.5 — insert — ambiguity — offset-less `to_iso8601` interpreted as UTC; logical-clock-derived timestamps serialize with 3 fractional digits only when nonzero — `validation.py:97-110`, `db.py:63-68`, `response.py:31-32`
- §2.6 — insert — ambiguity — all date request fields must be ISO `YYYY-MM-DD` valid calendar dates else `ERR_INVALID_REQUEST` — `validation.py:10,70-81`
- §2.7 — insert — ambiguity — totals resync refreshes `updated_at` without bumping `version`; deactivation/window-approval cascades resync totals with no version increment — `domain.py:249-261`, `physicians.py:87-88`, `windows.py:99-100`
- §3.1 — insert — ambiguity — `holiday_dates` must be an array of valid ISO date strings else `ERR_INVALID_REQUEST` — `programs.py:44-50`
- §3.1 — insert — ambiguity — tuning knobs (rates, multipliers, points, band, cutoff, lead) accept any value of their type without range validation — `programs.py:72-86`
- §3.2 — insert — ambiguity — supplied `moonlight_cap_hours` must be strictly positive else `ERR_INVALID_REQUEST` — `physicians.py:32-34`
- §3.2 — revise — ambiguity — deactivation swap cascade covers swaps whose **offerer or claimant** is deactivated (§3.2 previously enumerated only claimant; §3.4 already pinned both) — `physicians.py:79-86`
- §3.3 — insert — ambiguity — projected-pay premium tier evaluated on projected hours over the same strictly-before-slot-date rolling window — `domain.py:161-170,229-236`
- §3.4 — insert — ambiguity — claim dereferences caller's `X-User-ID` as a registered physician; unregistered → `ERR_PHYSICIAN_NOT_FOUND` — `swaps.py:104`
- §3.4 — insert — ambiguity — equity check: post-swap mean recomputed over post-swap population and rounded half-up to 2dp before comparison — `swaps.py:162-186`
- §3.4 — insert — ambiguity — `decline_reason` set to supplied value or null when absent — `swaps.py:193-199`
- §3.5 — insert — ambiguity — cancelling the very assignment that resolved a gap re-opens that same gap record (OPEN, `resolved_by_assignment_id` cleared, `reason`/`detected_at` re-stamped) instead of creating a new one — `domain.py:361-374`
- §3.5 — revise — ambiguity — `items` is an object keyed by the five item names; begin-credentialing responds with the updated requisition — `requisitions.py:130-140`
- §3.5 — insert — ambiguity — fiscal-gate breach on the fifth item rejects the whole completion; item not stamped, case stays IN_PROGRESS — `cases.py:84-91`
- §3.6 — insert — ambiguity — fairness `entries` carry `physician_id`/`full_name`/`prospective_points`/`actual_points`, ordered by physician `created_at`; empty population → totals and means 0.00 — `domain.py:457-492`
- §3.6 — revise — ambiguity — coverage `dates` entries carry the nine named fields, ascending date order — `domain.py:495-533`
- §3.6 — insert — ambiguity — reconciliation does not alter gaps, requisitions, cases, or swaps — `programs.py:184-194`

### Mismatch-revisions (PRD said X → revised to impl's Y)

- §2.11 — revise — mismatch — ladder claimed to be the sole fixed order; added that §3 narratives state actual per-endpoint sequences and that resources needed for ownership checks are loaded first (their 404 precedes `ERR_OWNERSHIP_VIOLATION`, remaining body validation follows) — `assignments.py:152-156`, `windows.py:108-110`, `swaps.py:52-56,245-247`
- §3.2 — revise — mismatch — approve-window guard order swapped to covers-served (level 8) before window-overlap (level 9), matching impl and the ladder — `windows.py:78-92`
- §3.3 — revise — mismatch — activation check order changed to SCHEDULED → activation window → BACKUP-slot (was BACKUP-slot before window) — `assignments.py:157-169`
- §3.4 — revise — mismatch — swap-cancel clauses reordered to ownership-then-POSTED, matching impl's check order — `swaps.py:245-250`
- §3.5 — revise — mismatch — propose-candidate guard order changed to ACTIVE → unavailability → overlap → LOCUM → specialty (was LOCUM/ACTIVE/specialty first) — `requisitions.py:97-112`
- §3.5 — revise — mismatch — complete-item check order changed to case-active → prerequisite → deadline → already-completed (was deadline before prerequisite) — `cases.py:64-80`

Everything else in the implementation — endpoint/role matrix, all default values, boundary semantics (exact-fit cap, equality-at-cutoff/deadline/window_end, strict inequalities for feasibility/expire/execute), pay formula and single rounding step, per-slot point rounding, rotation ordering and tie-breaks, cascade effects, fiscal gate formula (current reserve + new projected, including at swap execute), and response envelope shapes — was already uniquely pinned by the PRD and required no change.
