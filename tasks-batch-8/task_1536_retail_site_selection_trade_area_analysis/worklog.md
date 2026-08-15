# Worklog — task_1536_retail_site_selection_trade_area_analysis

## Step 1: Create Task Directory — 2026-08-13T20:22:12.000Z

Task directory `tasks/task_1536_retail_site_selection_trade_area_analysis/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T20:22:12.000Z

Scaffold generation complete for task 1536. All three files are written and the linter is clean on the final run.

**Output files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1536_retail_site_selection_trade_area_analysis/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1536_retail_site_selection_trade_area_analysis/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1536_retail_site_selection_trade_area_analysis/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts**
- Entities: 15 (Vote is append-only with `common_fields: false`; all others versioned)
- Endpoints: 69 (flat topology under `/api`, incl. `POST /api/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- State machines: 13 (incl. cyclic LOI SENT↔COUNTERED rounds, Site REJECTED→DRAFT revision loop, Market QUALIFIED↔SATURATED posture loop)
- Calculations: 10 (incl. dual-variant GRAVITY/ANALOG forecast, dual-variant FLAT_BAND/DISTANCE_DECAY cannibalization, pinned-order nested-rounding effective rent, circular-order market screening)
- Validations: 36 ordered rows across 10 priority tiers (auth → role → existence/shape → OCC → state → safety → constraint → temporal → referential → fiscal)
- Errors: 36 (one planned error, ERR_REVIEW_ALREADY_OPEN, was deleted mid-design as structurally unreachable — the site leaves FORECAST_LOCKED atomically at submit)
- Roles: 7 (CommitteeMember/CommitteeChair are `entity_backed:CommitteeMember`, enabling the sponsor-segregation checks)
- Difficulty instances: 24 (every one of the 9 rules has 2–3; all `assert` numerics pre-computed via Python — e.g., gravity gross 5,724,375,000 vs analog 1,100,000,000; flat vs decay cannibalization 350,000,000 vs 230,533,333; effective rent 19,125,555 cents)
- Corner instances: 65 active + 17 `excluded_because` stubs (82 total)

**Notable design decisions**
- Hardest-tier levers: depth-4 transitive cascade (model re-lock → model supersede → forecast supersede → review expiry → site regression), OCC on Site.version (create-with-supersede lock) and CommitteeReview.version (ballot-against-stale-tally), both lint-verified as `${var}`-driven.
- Adversarial boundaries everywhere pinned: inclusive 1500bp GREEN / exactly-90% budget cap / exactly-25% cannibalization cap / strict `>` 60% approval with abstain-excluded denominator / inclusive quorum / half-open LOI windows (adjacency allowed) vs closed+7-day-buffer crew windows / exactly −2000bp miss / 69.95-vs-70.00 visit score / fixed default clock proved by a no-clock-call rejection test.
- Segregation of duties: deal sponsor can neither vote on nor ratify their own review (including the sponsor-is-chair case).
- `scaffold_lint.py` verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (69 endpoints, 15 entities, 24 + 65 instances, 1515 calls scanned, 0 violations).
- Self-consistency script additionally verified: every catalog error is referenced by a validation or transition, every endpoint role is declared, every enum value is produced by a transition, and no forbidden concurrency vocabulary appears anywhere.

## Step 3: Copy Shared Files — 2026-08-13T20:23:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1536_retail_site_selection_trade_area_analysis/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T20:26:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1536_retail_site_selection_trade_area_analysis/workspace/PRD.md`. The two difficulty-design files were not opened, nor was any sibling task.

**Line count:** 350 lines.

**Section list:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination & Collection Filtering, 2.4 Resource Identity/Timestamps/Versions, 2.5 Monetary Units & Rounding Discipline, 2.6 OCC, 2.7 Validation Order & Error Precedence, 2.8 Logical Clock & Deadline Sweeps, 2.9 Market Portfolio Ledgers, 2.10 Terminal-State Lockdown
- §3 Business Logic (9 subsections): market onboarding/screening/store roster; site intake & screening gate; trade-area modeling & model-lock cascade; site visits; sales forecasts; committee review/voting/ratification; LOI negotiation; lease/crew/milestones; post-opening performance & close-out
- §4 Endpoint Definitions (69-row, 4-column table), §5 Error Code Catalogue (36-row, 2-column table)

**Coverage confirmation (all verified mechanically against the scaffold):**
- Contract 1: 124/124 required field names present in backticks (all entity fields, request-body keys, query params, path params, envelope fields). Two gaps found on first pass (`market_status`, `crew_status`) were repaired and the diff re-run to empty.
- Contract 2: all 10 calculations, 13 state machines (every transition with preconditions and side effects), both OCC rules (write endpoint + `expected_site_version`/`expected_review_version` + `ERR_STALE_VERSION`/412), the 10-layer validation priority order, and all applies-to scopes expressed in prose.
- Contract 3: §3 scanned 534 backtick tokens — zero path tokens, zero bare HTTP methods, zero method+path combos.
- Endpoints: 69/69 in §4 with role columns matching the scaffold (zero mismatches); errors: 36/36 in §5 with correct HTTP statuses; all 36 error IDs also named in §2/§3 prose; all enum/state values present.

**Notable Zero-Silence decisions (made explicit so rules stay uniquely derivable):**
- Clock boundary asymmetry: LOI create/send require end date *strictly after* the clock date, while counter/resend/accept permit the clock date *on or before* the end date; sweeps fire only when the deadline is *strictly before* the new time. `DECIDED` reviews are explicitly not clock-swept (cascade-only).
- Inclusive boundaries stated per rule: exactly 60.00 qualifies; exactly 70.00 passes the visit gate; exactly −2,000 bp is a miss; exactly 25% cannibalization passes; exactly 105% drift ceiling passes; exactly 90% budget cap passes; count exactly equal to target is saturated.
- Vote resource explicitly carries only `id` and `created_at` (no `updated_at`, no `version`).
- Half-open exclusivity windows with adjacency allowed; overlap re-checked at both LOI create and send; crew build windows closed-interval with a 7-day gap where exactly 7 days is permitted (conflict when new start falls on or before 6 days after the other end).
- Committee math pinned: abstentions excluded from both the percentage denominator and quorum; zero non-abstain ballots → `REJECT`; exact 60% → `REJECT`; exact integer arithmetic.
- Effective-rent rounding order pinned step-by-step (per-year psf rounded before per-year rent, year-one monthly rounded before free-rent multiplication); cannibalization rounded per store before summation; model-lock cannibalization snapshot frozen against later store closes while forecast lock recomputes live.
- Startup clock default 2026-08-01T00:00:00Z with explicit no-wall-clock-fallback; revise cascade supersedes `DRAFT` as well as `LOCKED` models; at-most-one-non-terminal-review-per-site framed as a structural invariant with no error id, per the scaffold note.

## Step 6: Generate Implementation — 2026-08-13T20:58:00.000Z

Implementation complete. Summary:

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1536_retail_site_selection_trade_area_analysis/workspace/implementation/`:

- `start.sh` — executable foreground launcher; guarded dependency install (`if ! python3 -c "import flask"`), then `exec python3 app.py`; honors `PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405/400 handlers
- `db.py` — in-memory store (dicts per entity, insertion sequence, logical clock)
- `errors.py` — ApiError + all 36 error-ID constants
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`)
- `middleware.py` — `X-User-ID`/`X-User-Role` validation (401) + per-endpoint role gating (403); `System` is a declared role but authorized on no endpoint → 403
- `util.py` — Decimal round-half-up helpers, strict body/date/datetime validators, FK existence (404), pagination (limit default 10, 1..100; offset default 0)
- `services.py` — all 10 calculations, ledger sync (`open_store_count`/`committed_capex_cents` recomputed from defining status sets + saturation posture flip), withdraw cascade, serializers
- `routes/`: `markets.py` (markets+stores), `sites.py`, `models.py` (models+listings), `visits.py`, `forecasts.py`, `committee.py` (members+reviews+votes), `deals.py` (LOIs+leases), `build.py` (crews+milestones), `snapshots.py`, `clock.py`

## Endpoint count
All **69** endpoints from the scaffold endpoint table implemented (16 resource groups + `POST /api/_clock/set_current_utc`), including both OCC-guarded writes (`expected_site_version` on model lock, `expected_review_version` on vote cast → `ERR_STALE_VERSION` 412, checked at layer 4 before state checks).

## Logical clock default
Starts at exactly `2026-08-01T00:00:00Z` on every boot (`db.py` constant, never wall-clock). Entity `created_at`/`updated_at` and `api_request_timestamp` are also derived from the logical clock (ISO 8601, 3 fractional digits), so a fresh boot is fully deterministic. Clock-set sweeps: SENT/COUNTERED LOIs with `exclusivity_end_date` strictly before the new clock date → EXPIRED; OPEN reviews with `expires_at` strictly before the new time → EXPIRED + site IN_COMMITTEE → REJECTED (DECIDED reviews never swept).

## Storage approach
Pure in-memory module-level dicts (`db.Store`), empty at every process start — no seeding, no files, no DB. Votes correctly omit `updated_at`/`version` per PRD §2.4.

## Boot smoke-test result
Three smoke suites run against fresh `bash start.sh` boots (Flask 3.1.3 / Python 3.14):
- **Suite A (happy path, 107 checks): all pass** — full pipeline market → store → site → screening → model lock → visit → forecast lock → committee (quorum 2-of-2, sponsor segregation, OCC) → ratify (capex commit) → LOI send/counter/resend/accept (round numbers, agreed-rent pinning) → crew window buffer (6-day gap rejected, exactly 7 allowed) → lease execute (drift ceiling, final occupancy) → milestones (order enforcement) → open → snapshots (expected 415,541,667; variance −2781 in exact decimal; miss counting; UNDERPERFORMING at 2 consecutive misses; recovery) → close-out (ledger release)
- **Suite B (cascades, 53 checks): all pass** — four-link model-lock supersession (model/forecast/review/site regressions), clock-sweep review expiry → REJECTED, revise cascade, saturation flip both directions, validation-order layering (format band 422 masks market-not-qualified 409; overlap 409 masks window-past 422), YELLOW/RED occupancy gates + chair override, cannibalization cap inclusive boundary (exactly 25% passes), approve-then-withdraw capex invariant
- **Suite C (targeted, 15 checks): all pass** — DELETE listing 204 empty body, half-open exclusivity overlap (adjacency allowed), LOI clock expiry, terminal lockdowns, 50%-approve REJECT math

Plus targeted numeric verification: escalated effective rent (26,145,000 over 2yr/200bp/1 free month, pinned rounding order) and DISTANCE_DECAY exact-decimal per-store rounding (171,500) both exact. Final cold boot via `bash start.sh` from the implementation directory: HTTP-ready in ~1s, store empty, clock at the spec default.

One spec ambiguity resolved deliberately: within the priority-10 fiscal layer at submit-committee, check order follows the scaffold validations-table row order (RED → CHAIR_OVERRIDE → BUDGET_CAP → NO_ELIGIBLE_VOTERS); for ratify's layer-6 checks, chair authority (`ERR_NOT_CHAIR`) precedes segregation-of-duties, per the PRD §3.6 narrative.

## Step 5: Generate Unit Tests — 2026-08-13T21:55:00.000Z

Generation complete and validated end-to-end.

## Summary — task_1536_retail_site_selection_trade_area_analysis

**Totals: 113 tests — Queue A (Difficulty): 48 (24 instances × 2 each); Queue B (Corner): 65 (all 65 non-stub instances × 1 each).** Every instance translated; zero skipped.

**Instances skipped:** none. All 24 difficulty instances and all 65 non-stub corner instances passed the PRD-first two-condition filter (every rule is verbatim-covered in PRD §2/§3 with uniquely-derived outcomes). All 17 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.

**test_helpers/ files:** `__init__.py` (barrel), `types.py` (23 enums + 15 TypedDicts; `Vote` correctly omits `updated_at`/`version`), `api_client.py` (69 endpoint methods), `api_errors.py` (36 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity + ledger invariants; nullable computed fields read via `.get()`), `factories.py`, `constants.py`, `test_users.py` (shared headers + mandatory `make_committee_member_headers`/`make_committee_chair_headers` per-instance builders for the entity-backed roles), `fixtures.py` (full 5-tier pipeline ladder: market → screened → modeled → scored → forecast-locked → in-committee → approved → LOI → lease → build-out → open → measuring → underperforming; OCC-threading `lock_model`/`cast_ballot`; roster-reuse support).

**test_suite/ files:** `conftest.py` + 11 domain-clustered files (`test_01_markets_and_screening` … `test_11_api_conventions`).

**Notable translation decisions:**
1. **Chair-singleton roster reuse** — `create_in_committee_site` accepts an optional `roster=`; multi-site tests (crew-window buffer, temporal-beats-referential, budget-cap) share one committee roster, since the PRD's chain-wide single-active-chair rule rejects a second roster. (Caught and fixed during live validation: the second site's roster creation was failing with `ERR_CHAIR_CONFLICT`.)
2. **Unset-field assertions** — "score fields unset"/"lock-time fields unset" are asserted via `.get() is None` so both explicit JSON null and key omission pass (PRD says "unset" without pinning serializer shape).
3. **`occupancy_ratio_tiered_branching`** — the instance's `chair_override == true` echo assertion on the review response was dropped (PRD never states the review serializer echoes that input); the instance's core branch behavior (422 without override, 201 OPEN with E=1/quorum=1 with it) is fully asserted.
4. **Vote OCC determinism** — sequential form used (fresh version re-read before each ballot; stale cast asserts 412), per the skill's OCC guidance.

**Verification performed:**
- All 113 docstrings: exactly one terminal `Design:` line each; all tags resolve to real instances with correct queue/section/rule (scripted audit).
- All 166 quoted PRD citations grep verbatim (whitespace-normalized) against `workspace/PRD.md`.
- No `skip`/`skipif`/`xfail`; no scaffold references in comments; pyflakes-clean.
- **Live run: `prd-bench-local-run --isolation per-test-server` → 113/113 passed** (148s) against the existing `workspace/implementation`. (Two earlier full-run attempts errored 113/113 at setup due to host contention plus a relative `--start-command` path that the runner's restart hook could not resolve from its own cwd — both environmental, resolved by the absolute `cd … && bash start.sh` form.)

## Step 7: Test-Iterate Loop — 2026-08-13T22:05:00.000Z

All 8 rounds completed cleanly — 113/113 passed in every round, 0 failed, 0 errors, 0 skipped. My first verification script used wrong key names (`outcome`/`nodeid` instead of `status`/`name`); the corrected check confirms zero non-passing tests anywhere. The "Killed" lines in the interim interleaved console output were transient display artifacts — every round's runner completed and reported full results.

## Summary

- **Iterations run**: 1 (single 8-round parallel stability sweep; no fixes needed).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `implementation/`**: none.

The task at `/home/ubuntu/github/CodingPRD/tasks/task_1536_retail_site_selection_trade_area_analysis` is stable: all 113 tests in `test_suite/` pass against the implementation in `workspace/implementation/` across all 8 concurrent rounds under `--isolation per-test-server`. The pre-existing implementation and test artifact were already mutually consistent and PRD-faithful, so no diagnostic step beyond STEP 0 was required.

Orchestrator verification: read all 8 `workspace/implementation/results.{1..8}.json` files directly — each reports passed=113, total=113 with all tests status=passed.

## Step 8: Finalize PRD — SKIPPED — 2026-08-13T22:06:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determines every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-13T22:20:00.000Z

All 19 diff hunks are single-line, in-paragraph edits. The work is complete. Here is the summary.

## Summary

**Source:** `PRD.md` (350 lines, 57,093 chars) — `PRD_FINALIZED.md` absent as expected. Copied to `PRD_COMPLETED.md` (350 lines, 59,970 chars). **Char delta: +2,877**; line count unchanged (all edits in-paragraph, no new sections).

**Counts:** 20 changes total — 16 ambiguity-pins, 4 mismatch-revisions.

**Changes:**

- §2.1 — revise — ambiguity — pinned that the `is_chair` condition for `CommitteeChair` identity is verified only where chair authority is exercised (ratify); a non-chair `ACTIVE` member presenting `CommitteeChair` may still cast votes as an ordinary member — `implementation/middleware.py:30-47`, `implementation/routes/committee.py:127-131,176-182`.
- §2.1 — insert — ambiguity — a request bearing `X-User-Role: System` passes authentication (role is declared) but is authorized on no endpoint → `ERR_FORBIDDEN_ROLE` (403) — `implementation/middleware.py:10-18,45-46`.
- §2.2 — insert — ambiguity — `api_request_timestamp` is stamped from the logical clock, not wall-clock — `implementation/response.py:9-15`.
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400); `has_more` = `offset` + returned page size < `total_count`; `created_at` ties broken by creation order — `implementation/util.py:183-221`.
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock — `implementation/services.py:15-29`.
- §2.7 (layer 3) — revise — mismatch — body is checked field-by-field in endpoint reading order with each FK resolved at the point it is read; pinned the model-creation interleave (scalar shape before `store_drive_times` store-id resolution; all store ids resolved before any `drive_minutes` shape check) — `implementation/routes/models.py:38-66`.
- §2.8 — insert — ambiguity — the clock endpoint applies `to_iso8601` as given, with no monotonicity check — `implementation/routes/clock.py:23-25`.
- §2.10 — revise — mismatch — added `RETIRED` for a construction crew to the terminal-state list — `implementation/routes/build.py:61-62`.
- §3.1 — insert — ambiguity — evaluation accepted only from `SCREENING`/`DISQUALIFIED`; evaluating `QUALIFIED`/`SATURATED` → `ERR_INVALID_STATE` — `implementation/routes/markets.py:92-96`.
- §3.1 — insert — ambiguity — closing a market in `SCREENING`/`DISQUALIFIED`/`SATURATED`, or a `QUALIFIED` market with pipeline sites, → `ERR_INVALID_STATE` — `implementation/routes/markets.py:109-118`.
- §3.1 — insert — ambiguity — store registration imposes no market-status gate — `implementation/routes/markets.py:129-152`.
- §3.2 — revise — mismatch — reordered the screening-gate enumeration to the applied order: format band → market `QUALIFIED` → rent cap — `implementation/routes/sites.py:90-105`.
- §3.2 — insert — ambiguity — site intake imposes no market-status gate — `implementation/routes/sites.py:50-65`.
- §3.3 — insert — ambiguity — model lock additionally requires the site in a model-accepting stage (`SCREENED`…`IN_COMMITTEE`), else `ERR_INVALID_STATE` — `implementation/routes/models.py:117-119`.
- §3.5 — insert — ambiguity — zero-division fallback for occupancy ratio: 0 when the annual occupancy total is also zero, else 9,999,999 bp; applies to the §3.8 final variant too — `implementation/services.py:205-209`.
- §3.6 — insert — ambiguity — the named sponsor must exist but need not be `ACTIVE` — `implementation/routes/sites.py:117,155-157`.
- §3.6 — revise — mismatch — fiscal-gate precedence reordered to impl: occupancy band gates (RED, then YELLOW-override) → capital budget cap → eligible-voter pool — `implementation/routes/sites.py:138-161`.
- §3.7 — revise — ambiguity — a new LOI's `effective_annual_rent_cents` is unset until the first send — `implementation/routes/deals.py:101`.
- §3.8 — revise — ambiguity — milestone completion records the client-supplied `actual_date` from the request body — `implementation/routes/build.py:121-122`.
- §3.9 — insert — ambiguity — zero-expectation fallback for `variance_bp`: 0 when `actual_sales_cents` is also zero, else 9,999,999 bp — `implementation/routes/snapshots.py:93-94`.

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1536_retail_site_selection_trade_area_analysis/workspace/PRD_COMPLETED.md`

Notable verified-as-already-pinned areas (no change): the full model-lock four-link cascade, OCC guards and their layer-4-before-5 ordering, all calculation formulas (screening chain, GRAVITY/ANALOG gross, cannibalization variants, effective-rent rounding sequence, occupancy bands, quorum/outcome integer arithmetic, drift/budget/cannibalization caps with inclusive boundaries), LOI half-open window semantics, crew 6-day buffer rule, endpoint/role matrix, error catalog, and all list-endpoint filters.
