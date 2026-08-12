# Worklog — task_1150_renaissance_faire_seasonal_attraction

## Step 1: Create Task Directory — 2026-08-11T02:43:00.000Z

Pre-assigned output folder `tasks/task_1150_renaissance_faire_seasonal_attraction` with `workspace/` subdirectory already exists (auto-index scan skipped per instructions). Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T03:23:00.000Z

Scaffold generation complete and lint-clean. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1150_renaissance_faire_seasonal_attraction/`):
- `SCAFFOLD.yaml` — 2235 lines (§1.0–§1.7; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 699 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1381 lines (single top-level key `scaffold_corner_design`)

**Counts:**
- Entities: 15 (Season, FaireDay, Performer, CastContract, RehearsalSlot, Vendor, VendorApplication, BoothAssignment, FoodPermit, TicketOrder, Ticket, RainCheck, VolunteerShift, ConductCase, BuildTask)
- State machines: 13
- Calculations: 11
- Validation priority rows: 9
- Endpoints: 82 (incl. `POST /_clock/set_current_utc` with pinned startup default `2026-05-01T00:00:00Z`)
- Errors: 80
- Roles: 10 (FaireOperator, CastDirector, VendorCoordinator, GateAgent, VolunteerCoordinator, Performer [entity_backed], Vendor [entity_backed], Volunteer, Guest, Any)
- Concurrency rules (OCC): 2 (`season-config-stale-edit`, `order-reprice-stale-version`)
- Difficulty-design instances: 18 (all 9 §0.5 rules × 2, honoring each differentiation clause)
- Corner-design instances: 61 total = 57 active + 4 `excluded_because` stubs

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(739 §1.8+§1.9 calls scanned; checks a–f all pass.)

**Harder-than-expert design highlights:** posture-driven Season gating (BLOCKED/CONDITIONAL/READY derived from build-task DAG, food-permit coverage, volunteer-hour threshold) layered over temporal windowing; two dual-variant calculation domains (booth fee provisional-vs-settlement 24000 vs 23849; cast payout accrual-vs-guarantee 50000 vs 60000); combinatorial formulas in all three modes (tiered group pricing with conditional fee; per-day-vs-aggregate rounding pinned at 1287≠1286; pinned evaluation order for the surcharge-on-subtotal booth settlement); depth-3 transitive cascades from two distinct triggers (weather cancellation → shift cancel → hours recompute → posture flip; conduct revoke → permit revoked → booth suspended → posture flip); two compensating invariants over different conserved quantities (admission count across cancel/redeem pairs; refunded+retained==total in cents); all fixture arithmetic in asserts pre-computed as literals.

Note: the task directory already contained a `worklog.md` and `workspace/` (created before this run by the orchestrator); I did not touch them. No sibling task directories were read at any point.

## Step 3: Copy Shared Files — 2026-08-11T03:24:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1150_renaissance_faire_seasonal_attraction/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T03:35:00.000Z

PRD generation complete and verified. Report below.

## Deliverable

- **File**: `/home/ubuntu/github/CodingPRD/tasks/task_1150_renaissance_faire_seasonal_attraction/workspace/PRD.md`
- **Size**: 419 lines, 8,786 words, 61.9 KB. Ends at §5 with no audit footer.
- **Constraint compliance**: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling `task_*/` directory was touched.

## Section list

- §1. Introduction (2 paragraphs — business context + system philosophy)
- §2. Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 Logical Clock, Calendar Dates, Lazy Expiration · 2.6 Season Readiness Posture · 2.7 Money/Integer Cents/Rounding · 2.8 Optimistic Concurrency Control · 2.9 Validation Order & Resource Existence · 2.10 Conserved Ledgers (admissions + refund invariants)
- §3. Business Logic (9 subsections): 3.1 Season setup/build/open · 3.2 Cast contracts/rehearsals/pay · 3.3 Vendor jury/booths · 3.4 Food permits · 3.5 Ticket orders/pricing/payment · 3.6 Faire-day ops + weather cascade · 3.7 Gate redemption/rain checks/voids · 3.8 Volunteer staffing · 3.9 Conduct/strike/close
- §4. Endpoint Definitions (82 rows, 4 columns)
- §5. Error Code Catalogue (80 rows, 2 columns)

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + path params: 82 required, 82 present, 0 missing
- endpoints[].request_body inputs: 63 required, 63 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority layers: 9 checked, 9 expressed in ordered §2.9 prose (incl. OCC-after-state in layer 5, 422 exceptions named), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (edit surface + expected_season_version/expected_order_version + ERR_STALE_VERSION 412 named), 0 missing
- state_machines[].transitions: all transitions of 13 machines checked, fully expressed (from/to, preconditions with error_id, side effects), 0 missing
- calculations[]: 11 checked, 11 fully expressed in reconstructible prose (tier rates 120/80/50, group tiers 10/15/20% at 1x/2x/4x, 150-cent fee, 25% rain credit with per-day rounding + rejected aggregate variant, 5%/20,000-cent PRIME surcharge, 5,000-cent/hour shortfall, 0.5/0.3/0.2 jury weights at 2dp, guarantee floor, posture threshold with inclusive boundary, both invariants), 0 missing
- validations[] conditions: all 80 error_ids matchable to prose triggers in §2/§3 (verified mechanically: 80/80 present before §4), 0 missing
- endpoints[].side_effects / applies_to: 82 checked, 82 expressed (weather 5-part cascade, strike/close cascades, conduct sanction cascades, waitlist promotion selector, lazy expirations), 0 missing
- entities[].fields[] structured content: defaults/initials/ranges reconstructible (posture BLOCKED + counters 0 + version 1 at create; appeal_used false; jury_score/countered/permit_number null-until; refunded 0/retained = total; all numeric ranges), 0 missing
- sibling-branch symmetry: 12 groups checked (6-way terminate, 3x3 decide matrix, 4-way withdraw, dual confirm/settle/inspect/close-out branches, refund partial/full, redemption-status siblings, PERFORMING entry from ACCEPTED+REHEARSING), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 675
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional precision checks: §2.2 emitted byte-identical to `section-2.2-response-structure.md` (PASS); all 87 enum/state strings present exactly (initial scan caught `TERMINATED` missing — fixed in §3.2); all 10 role names backticked with `identity:` fields translated (Performer/Vendor entity-backed, seven opaque roles individually named incl. `Any`); pagination defaults (10/1/100/0), `created_at`-ascending sort, and meta fields stated; zero fuzzy words and zero operator-syntax tokens (two "Around" sentence-starters reworded during repair pass).

## Coverage audit (scaffold §1.1–§1.7 → PRD)

- **§1.1 Entities** → all 15 entities' fields woven into §2.4 (common fields) and §3.1–§3.9 narratives; computed fields carry their derivations (`season_weeks` ceil-weeks §3.1, `tickets_sold_count` VALID+REDEEMED count §3.5, posture/volunteer-hours §2.6, both invariants §2.10).
- **§1.2 State machines** → 13 machines projected as lifecycle prose across §3; every precondition paired with its scaffold error_id; system transitions (attendance→REHEARSING, open→PERFORMING, strike→COMPLETED, permit/booth suspension, order redemption recompute, lazy expirations) all stated as cascades.
- **§1.3 Calculations** → all 11 expressed in precise prose with constants embedded in context; rounding placement pinned per rule; the rejected aggregate-rounding variant explicitly noted in §2.7.
- **§1.4 Validations** → the nine-layer priority cascade is §2.9 verbatim-in-prose with left-to-right path existence then body-FK existence; per-rule triggers restated at their workflows in §3.
- **§1.5 Endpoints** → §4 routing table (82 rows, Method/Path/Description/Roles only); status-code convention paragraph (201 creates / 200 modifications); clock endpoint described as a capability in §2.5 with its path only in §4.
- **§1.6 Errors** → §5 two-column catalogue (80 rows) with no trigger conditions; every ID also surfaces in §2/§3 narrative.
- **§1.7 Roles** → §2.1 enumerates all 10 roles, both headers, and the three auth errors; ownership semantics tied to `performer_id`, `vendor_id`, `buyer_email`, `volunteer_handle`.

**Zero-Silence Rule check**: every scaffold behavior appears as a full PRD sentence — no identifier is present without its rule, and no rule was dropped during prose rewriting (mechanical diff + manual walk of the six high-risk Contract-2 categories and the tail).

## Step 5: Generate Unit Tests — 2026-08-11T04:04:00.000Z

Generation complete. All files on disk, compiled, and audited.

## File inventory (4,922 lines total)

**test_helpers/ (9 files, 1,757 lines):**
- `types.py` (403) — 15 entity TypedDicts (all carry id/created_at/updated_at/version per common_fields) + 20 status/role enums
- `api_client.py` (269) — `ApiClient(GenericApiClient)` with 63 methods covering all 82 PRD endpoints
- `api_errors.py` (181) — all 80 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (176) — per-entity `assert_*` + `assert_order_money_invariant` + `assert_outstanding_admissions`
- `factories.py` (164), `constants.py` (44) — input-field factories; PRD-pinned constants (fee 150, tier rates 120/80/50, RAIN_CREDIT_PCT 0.25, surcharge 5% @ 20000, shortfall 5000/h, 15-min buffer)
- `test_users.py` (44) — TEST_USERS for all 10 roles + `make_performer/vendor/volunteer/guest_headers` builders for entity-backed/handle ownership threading
- `fixtures.py` (640) — tiered composites: primitive creators, state progression (`make_build_season`/`make_open_season`/`make_operating_day`), jury/booth/permit stacks, paid orders, rain-check setups, and heavy scenario builders (`setup_booth_fee_scenario`, `setup_all_rain_cast_scenario`, `setup_weather_cascade_scenario`, `setup_conduct_revoke_scenario`, `setup_shortfall_scenario`, `setup_conservation_scenario`, `setup_priority_raincheck_scenario`)
- `__init__.py` (36) — barrel export

**test_suite/ (18 files, 3,165 lines):** `conftest.py` + 17 numbered test files organized by concern (season config/OCC, envelope/existence, faire-day lifecycle, cast, rehearsals, jury, booth booking, booth fees, permits, pricing, payment, refunds, gate/rain-checks, volunteers, conduct, build tasks, RBAC).

## Test counts

- **Total: 94 tests** (pytest-collected cleanly)
- **Queue A (Difficulty): 36 tests** — all 18/18 instances covered with exactly ≥2 tests each
- **Queue B (Corner): 58 tests** — 56/57 non-stub instances covered (occ_season_config and occ_order_reprice each get 2 tests: success + stale-replay legs)

## Skipped instances (gaps stay gaps)

- `Corner/validations/permit_inspection_attempt_cap` — **PRD-silent on the asserted value.** PRD §3.4 says only "the system's fixed maximum number of inspection attempts" without naming 2; two PRD-only implementers could pick different caps, so "second FAILED → FAILED_FINAL; third inspect rejected" is not uniquely derivable. Not weakened, not placeholder-emitted.
- 4 `excluded_because:` stubs correctly NOT translated: `jury_score_weighted_value`, `group_size_and_refund_bounds_covered_by_difficulty`, `layer_cascading_side_effects_covered`, `layer_dual_variant_calculation_covered` — all four difficulty-instance pointers resolve to real §1.8 names.

## Stage-2 tag-audit result

- All 94 test docstrings end with exactly one `Design:` tag as the final line; 0 untagged, 0 dual-tagged, 0 dangling tags (two section mislabels — `errors` vs `validations` — were caught by the audit and fixed)
- All 150 quoted citation spans of ≥8 words survive a whitespace-tolerant literal grep of PRD.md (3 fused-sentence citations were caught and split into separate verbatim quotes)
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold"/table/§1.x references in generated code
- Every `.py` file passes `py_compile`; full suite collects under `PYTHONPATH=.` with no import errors

## Step 6: Generate Implementation — 2026-08-11T04:05:00.000Z

Implementation complete. Final report:

## File inventory — `workspace/implementation/` (3,469 lines total)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher: guarded `pip install` (no-op once Flask present), `exec python3 app.py`; reads `$PORT` (default 10000), binds 0.0.0.0. Executable (`-rwxrwxr-x`). |
| `requirements.txt` | 1 | `flask>=2.2` |
| `app.py` | 48 | App factory, ApiError/404/405/500 handlers, blueprint registration, `app.run(host="0.0.0.0", port=$PORT)` |
| `db.py` | 51 | In-memory store (15 dicts keyed by id, empty at boot), logical clock defaulting to `2026-05-01T00:00:00Z` |
| `errors.py` | 116 | `ApiError` + all 80 catalog error IDs |
| `response.py` | 57 | Envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list pagination fields in meta; error shape |
| `middleware.py` | 107 | Layer-1/2 auth (`X-User-ID`/`X-User-Role`), role gating, ownership, body parsing, 404 loaders, `limit`/`offset` parsing (default 10, 1–100) |
| `util.py` | 212 | ISO-8601 parse/format (3 fractional digits), Decimal helpers, `ROUND_HALF_UP`, `touch`/`mutate`/`assign` version discipline, shape validators |
| `services.py` | 516 | Readiness posture derivation, lazy permit/rain-check expiry, all cascades (weather 5-part, strike, close sweep, ban-guest, revoke-permit, waitlist promotion), all 11 calculations with pinned constants |
| `routes/` (16 modules + `__init__`) | 2,150 | One module per resource group, all 82 endpoints |

## Verification results

- **Route coverage**: 82/82 (method, path) pairs from SCAFFOLD.yaml `endpoints` registered — **none missing** (the one extra route is Flask's built-in `/static` GET). [Orchestrator independently re-verified: 82/82 normalized route pairs match, 0 missing, 0 extra.]
- **Compile**: `python3 -m py_compile` passes on all 24 `.py` files.
- **Boot smoke test**: `PORT=17900 bash start.sh` → `GET /seasons` with auth headers → HTTP 200 in ~2 s; missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` with correct error envelope.
- **Behavioral smoke**: two scripted end-to-end suites passed — (1) full season lifecycle (PLANNING→BUILD→OPEN→STRIKE→CLOSED) including OCC 412/409 ordering, group-tier pricing (10%/15% + DAY convenience fee), weather-cancel cascade (rain checks 1:1, outstanding conserved, volunteer-hours removal, posture re-derivation), rain-check redemption, rehearsal attendance → REHEARSING → PERFORMING, guarantee-floor payout minus shortfall penalty, PRIME surcharge settlement, lazy rain-check expiry; (2) refunds/money invariant (PARTIALLY_REFUNDED→REFUNDED, 422 over-retained), BAN_GUEST void cascade, waitlist promotion on release, per-day weather credit rounding (`rhu(2500×0.25/2)=313`), capacity 409, duplicate-application 409, rehearsal 15-min buffer overlap 409, linkage-invalid 409.

## Notable decisions on unpinned spec points

- `PERMIT_GRACE_DAYS=30`, `MAX_INSPECTION_ATTEMPTS=3` — named symbolically in the spec without numeric values; centralized in `services.py` for one-line adjustment if tests reveal pinned values.
- Validation layering follows PRD §2.9 strictly: headers → role → existence (path then body FKs in canonical order) → ownership → shape → state gates → OCC last within state layer → food-safety → clock gates → constraints → fiscal bounds.
- `version` increments exactly once per successful PATCH (edit + reprice applied via `assign` then a single `touch`); system-driven counter/posture changes bump versions only on actual value change.
- No seeding anywhere — store boots empty; all state is built via the API surface.

## Step 7: Run Tests and Iterate — 2026-08-11T04:24:00.000Z

## Summary

**Result: clean 8-round parallel sweep — 94/94 passed in every round, twice in a row** (the confirmation sweep ran under heavy shared-host load: load average 11 on 8 CPUs, with another benchmark task `task_1153` running concurrently).

### Iterations run
5 sweeps total (baseline + 3 fix iterations + 1 confirmation):
- Sweep 1 (baseline): 58/94 — 36 consistent failures
- Sweep 2: 87–88/94
- Sweep 3: 91–92/94
- Sweep 4: **94/94 × 8 rounds, CLEAN**
- Sweep 5 (confirmation, under load): **94/94 × 8 rounds, CLEAN**

### Tests deleted
**None.** Every failing test traced to a rule stated verbatim in PRD. No test asserted a scaffold-only rule, and no unique-derivability collapse was found among the failures.

### Fixes applied to `test_suite/` (test bugs — STEP 2; no `test_helpers/` changes needed)
All were setup-ordering bugs where the test issued a request that violates a PRD precondition, so the PRD-faithful implementation correctly rejected it. Fixed to be *more* PRD-faithful, never less:
- `test_03_faire_day_lifecycle.py::test_day_operation_error_ladder` — create the faire day before `open_season` (PRD §3.6: day scheduling requires season `PLANNING`/`BUILD`).
- `test_11_ticket_payment.py::test_ticket_order_parallel_dimensions_independent` — create the day before `open_season`, and place/pay the order before `open_gates` (PRD §3.5: DAY/GROUP orders require an `OPEN_FOR_SALES` day, not `OPERATING`).
- `test_12_refunds.py::test_refund_terminal_redemption_states_rejected` — create both days before `open_season`.
- `test_13_gate_and_rain_checks.py::test_redeem_ticket_not_valid_and_day_guards` — create both days before `open_season`.
- `test_12_refunds.py::test_refund_exceeding_retained_rejected` — the original asserted `ERR_REFUND_EXCEEDS_PAID` on a fully-`REFUNDED` order, but PRD §2.9 places the payment-state gate (`ERR_ORDER_NOT_UNPAID`, layer 5) before the fiscal bound (layer 9). Fixed to overshoot `retained_cents` by one cent on a still-`PARTIALLY_REFUNDED` order, which is the reachable path to the 422.

### Fixes applied to `implementation/` (STEP 3)
- `workspace/implementation/routes/seasons.py` — `begin_build` and `open_season`: re-derive the computed `readiness_posture` on the season transition / before the `READY` gate. Root cause of the 36-failure baseline: the initial `BLOCKED` stored at creation (PRD §3.1) persisted because no §2.6 enumerated trigger fired, so the gates read a stale value even when the §2.6 derivation (no BUILD tasks, `volunteer_min_hours=0`) yields `READY`. Re-derivation is idempotent and always reflects current inputs, so it never masks a genuinely blocked season.
- `workspace/implementation/routes/faire_days.py` — `open_sales`: re-derive posture before the `BLOCKED` gate (same root cause).
- `workspace/implementation/start.sh` — sentinel-guarded dependency install so repeat per-test server boots skip the ~210 ms `python3 -c "import flask"` spawn. This cut boot latency/contention during the 752-boot restart storm and eliminated the infra-level flakes (`could not be restarted` / `Connection reset by peer`) that appeared only when the shared host was loaded by other benchmark tasks.

No tests were weakened, no assertions downgraded, no skips/xfails added, and no implementation check required by PRD was removed.

[Orchestrator disk verification: all 8 `workspace/implementation/results.{1..8}.json` files present, every round reports passed=94 failed=0 total=94.]

## Step 8: Finalize PRD — 2026-08-11T04:27:00.000Z

The diff is exactly as intended: 3 lines touched, all others verbatim. Both files are 419 lines (0% line-count delta; changes are inline sentence insertions/revisions).

## Summary

**Line counts:** `PRD.md` 419 lines → `PRD_FINALIZED.md` 419 lines (0% line delta; 3 lines revised inline).

### Changes (all trace to the Step 3 implementation fixes in `<step_7_diff>`)

- **§2.6 (Season Readiness Posture)** — revise — appended: "It is also re-derived when the season moves from `PLANNING` to `BUILD`, and immediately before either outward gate below evaluates it, so both gates always act on the current derivation rather than a previously stored value." The existing trigger list and the "two outward gates" sentence are kept verbatim. Pins the stored-vs-computed ambiguity that caused the 36-failure baseline — `implementation/routes/seasons.py:180`, `implementation/routes/seasons.py:192-193`, `implementation/routes/faire_days.py:121-122`.
- **§3.1 (begin-build)** — revise — appended "; the transition re-derives the readiness posture per §2.6" to the begin-build sentence — `implementation/routes/seasons.py:177-180` (state gate first, then transition, then re-derivation).
- **§3.1 (open season)** — revise — "…and, the posture having been re-derived per §2.6 after that state check, the readiness posture to be `READY`…" — matches exact impl ordering: BUILD check → re-derive → READY gate (`implementation/routes/seasons.py:189-194`). The pre-existing "re-derived one final time" sentence stays verbatim (matches `season_open_cascade`, `services.py:402`).

### Step 7 items that required no PRD edit
- All five `test_suite/` fixes trace to rules stated verbatim in PRD (§3.6 faire-day scheduling requires `PLANNING`/`BUILD`; §3.5 DAY/GROUP orders require an `OPEN_FOR_SALES` day; §2.9 places the layer-5 payment-state gate `ERR_ORDER_NOT_UNPAID` before the layer-9 fiscal bound `ERR_REFUND_EXCEEDS_PAID` — verified in `routes/ticket_orders.py:221-231`). PRD already determines the behavior.
- `start.sh` sentinel-guarded install is pure boot infrastructure with no behavioral contract in PRD scope.

### Per-edit pre-edit search log (NO-NEW-MISMATCH)

**Edit 1 — §2.6 re-derivation sentence.**
(a) Subject: `readiness_posture` re-derivation triggers and gate-time evaluation.
(b) Enumerated every impl path via `grep -rn "rederive_posture\|readiness_posture"`: `services.py:125` (permit lazy-expiry), `services.py:357` (weather cascade), `services.py:402` (open cascade), `services.py:452` (revoke cascade), `services.py:467` (waitlist promotion), `faire_days.py:121-122` (open-sales gate), `food_permits.py:135` (issuance), `seasons.py:96/166/180/192-193` (init, PATCH, begin-build, open gate), `vendor_applications.py:133` (jury decision), `volunteer_shifts.py:128/149/168` (confirm/close-out/cancel), `build_tasks.py:97/195` (create/advance). Only reads of the stored value are the two named gates, so "two outward gates" remains true.
(c) Wording adjustment: phrased as additive ("also re-derived") and kept the original trigger list verbatim so loosely-covered sites like waitlist promotion (`services.py:467`) remain covered under "whenever one of its inputs moves" — no path narrowed or excluded.

**Edit 2 — §3.1 begin-build + open-gate clauses.**
(a) Subject: posture re-derivation on season transitions and before the `READY` gate.
(b) Paths: `seasons.py:170-197` (begin_build, open_season), cross-checked against `services.py:396-402` (`season_open_cascade` re-derives after contract promotion — the PRD's existing "one final time" clause) and the §2.6 gate sentence.
(c) Wording adjustment: for the open gate, wrote "re-derived … after that state check" to pin impl's exact ordering (state 409 before re-derivation before `ERR_SEASON_NOT_READY`), so a non-BUILD season still errors without side effects.

**Edit 3 — §3.6 open-sales gate clause.**
(a) Subject: posture re-derivation before the `BLOCKED` gate on open-sales.
(b) Paths: `faire_days.py:110-127` (order verified: day-`SCHEDULED` gate → season `BUILD`/`OPEN` gate → re-derive → `BLOCKED` gate → mutate); confirmed no other endpoint reads posture (grep in (b) of Edit 1).
(c) Wording adjustment: inserted the re-derivation clause as a parenthetical on the second gate only, preserving the "gated on the season twice over" order and leaving the day-state gate (`ERR_DAY_NOT_OPENABLE`) untouched, matching `faire_days.py:115-122` exactly.

Deliverable: `/home/ubuntu/github/CodingPRD/tasks/task_1150_renaissance_faire_seasonal_attraction/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-11T04:36:00.000Z

PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1150_renaissance_faire_seasonal_attraction/workspace/PRD_COMPLETED.md`.

**Size delta**: PRD_FINALIZED.md 419 lines / 62,355 chars → PRD_COMPLETED.md 420 lines / 65,954 chars (+1 line, +3,599 chars). No sections added; all changes are inline inserts/revisions.

**Counts**: 24 changes total — 21 ambiguity-pins, 3 mismatch-revisions.

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.1 — revise — ambiguity — header rejection now "missing, empty, or whitespace-only" — middleware.py:28
- §2.1 — insert — ambiguity — unrecognized role designators are not rejected up front: they pass `Any` shared reads and get `ERR_UNAUTHORIZED_ROLE` on restricted endpoints — middleware.py:37-46
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + twenty random alphanumeric characters — util.py:43-45
- §2.2 — insert — ambiguity — unrouted paths / wrong methods / unexpected failures answered in the error envelope with `ERR_INVALID_REQUEST` at 404/405/500 — app.py:27-38
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST` (400) — middleware.py:71-94
- §2.3 — revise — ambiguity — creation-timestamp ordering realized as strict insertion order (deterministic within the same millisecond) — middleware.py:106-107, db.py:41-43
- §2.3 — insert — ambiguity — `total_count` counts filter-matching resources; `has_more` = offset + returned items < total_count — response.py:36-48
- §2.4 — insert — ambiguity — version-increment discipline: no-op writes bump neither `version` nor `updated_at`; the two OCC edits bump exactly +1 even with unchanged values — util.py:85-100, seasons.py:163-164, ticket_orders.py:177-187
- §2.5 — revise — **mismatch** — midnight-UTC calendar fields are a convention; the server accepts/stores/compares any ISO 8601 instant without validating time of day — util.py:16-26 (no midnight check), seasons.py:79-82
- §2.6 — revise — **mismatch** — volunteer hours compared exactly as stored, no rounding ("at two decimal places" removed) — services.py:215, util.py:73-76
- §2.9 — revise — ambiguity — layer 1 restated as non-blank (missing/empty/whitespace-only) — middleware.py:28
- §3.1 — insert — ambiguity — dependency rules pinned: missing dep → `ERR_TASK_NOT_FOUND`, cross-season dep → `ERR_INVALID_REQUEST`, extending a `DONE` task → `ERR_TASK_NOT_ADVANCEABLE`, dep on a `DONE` task → `ERR_INVALID_REQUEST`, already-present ids skipped, creation-time duplicate ids collapsed — build_tasks.py:42-57, 92, 138-162
- §3.3 — revise — **mismatch** — withdrawal no longer glossed as "any non-terminal state": `JURIED_IN` (non-terminal per the duplicate-application rule) cannot be withdrawn — vendor_applications.py:36, 151-162; services.py:35
- §3.3 — revise — ambiguity — booth overlap checked only against live (`RESERVED`/`CONFIRMED`/`SUSPENDED`) residencies; `RELEASED`/`SETTLED` don't block — booth_assignments.py:42, 75-79
- §3.3 — revise — ambiguity — waitlist tie-break is earliest creation (insertion order per §2.3); promotion re-derives readiness posture like a `JURIED_IN` decision — services.py:455-468
- §3.4 — insert — ambiguity — stale `ISSUED` permits past expiry are expired on the spot before the duplicate-permit check, so they never block a fresh application — food_permits.py:67-75
- §3.4 — revise — ambiguity — `PERMIT_GRACE_DAYS=30` pinned; `permit_number` format `PERMIT-XXXXXXXX` (8 uppercase hex) pinned — services.py:29, food_permits.py:132-133
- §3.4 — revise — ambiguity — `MAX_INSPECTION_ATTEMPTS=3` pinned ("third and last permitted" attempt → `FAILED_FINAL`) — services.py:30, food_permits.py:137-140
- §3.5 — insert — ambiguity — order edit changing `faire_day_id` requires the new day `OPEN_FOR_SALES`, else `ERR_DAY_NOT_OPENABLE` — ticket_orders.py:153-160
- §3.5 — insert — ambiguity — manual void moves order to `VOID` only when no `VALID` tickets remain and ≥1 `VOID` exists; `FULLY_REDEEMED`/`RAINCHECKED`/`VOID` are sticky terminal states (minting a replacement into a `RAINCHECKED` order doesn't reopen it) — services.py:227-244, rain_checks.py:92-94
- §3.7 — insert — ambiguity — rain-check redeem ownership is evaluated after the body's `target_faire_day_id` passes existence/shape validation, before the four gates — rain_checks.py:66-83
- §3.7 — revise — ambiguity — `redeemed_at` stamped in the same ISO 8601 UTC three-fractional-digit format — tickets.py:73, util.py:29-32
- §3.9 — insert — ambiguity — upheld `REVOKE_PERMIT` with a no-longer-`ISSUED` linked permit still resolves `UPHELD` with the sanction recorded; the cascade is a no-op — conduct_cases.py:136-139
- §4 — insert — ambiguity — filters match by exact equality; `depends_on_task_ids` matches by membership; unrecognized query parameters ignored — middleware.py:97-103, build_tasks.py:109-111

All four known unpinned points from the brief were verified against the code and pinned (`PERMIT_GRACE_DAYS=30`, `MAX_INSPECTION_ATTEMPTS=3`, util.py version-bump discipline, 3-fractional-digit timestamps — the last was already pinned globally and extended to `redeemed_at`). Everything else in the implementation (endpoint table, state machines, cascades, calculation formulas, validation layering, error catalogue) matched PRD_FINALIZED.md uniquely and required no change.
