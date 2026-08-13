# Worklog — task_1389_truck_parking_reservation_network

## Step 1: Create Task Directory — 2026-08-13T03:04:00.000Z

Pre-assigned by pipeline invoker; directory and workspace/ already exist. Treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-13T03:55:00.000Z

Done. All three scaffold artifacts are generated, lint-clean, and self-consistent.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1389_truck_parking_reservation_network/`)

- **`SCAFFOLD.yaml`** — §1.0–§1.7 only (no design keys): fixed response envelope, 12 entities, 12 state machines + 2 OCC concurrency rules, 15 calculation rules, 21 priority-ordered validations, 56 endpoints, 31 error codes, 5 roles (Anonymous/Driver/FleetManager entity-backed or opaque per §1.7, SiteOperator/NetworkAdmin opaque).
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — `scaffold_difficulty_design:` with all 9 rule groups, 21 instances (dual_variant 2, combinatorial 3 across modes a/b/c, non_linear SM 2, cascades 3, priority conflicts 2, boundary 3, cross-entity 2, overlap 2, invariants 2).
- **`SCAFFOLD_CORNER_DESIGN.yaml`** — `scaffold_corner_design:` with 60 instances (56 active + 4 `excluded_because` stubs), spanning entities/state_machines/calculations/validations/endpoints/errors/rbac/complexity_layers/consistency_model.

## Design highlights (harder-than-expert features)

- **Two interlocked quota pools** (reservable vs first-come stalls) with half-open `[15:00Z, 11:00Z)` occupancy intervals and a built-in turnover gap; plus a third, night-granular bucket semantics for capacitated shower amenities (Rule 8 differentiation).
- **Dual pricing models**: RESERVED = dynamic `base × occupancy-tier × HOS peak-day multiplier` with posture-capped surge (DEGRADED from ≥3 open LIGHTING incidents clamps the multiplier to 1.0 — incident reporting feeds pricing); WALK_IN = flat base, no discounts.
- **Booking has parallel state dimensions** (lifecycle × billing); a NO_SHOW lifecycle-terminal booking still invoices its fee through the billing axis.
- **Transitive cascades**: ops-run no-show → strikes → SUSPENDED → future bookings auto-cancelled → waitlist re-offers (depth 4); fleet overdue → fleet SUSPENDED → authorizations auto-suspended (with manual-vs-auto restore distinction) → fleet bookings cancelled (depth 4); invoice paid → bookings PAID → loyalty earn (depth 3).
- **Compensating invariants**: stall free-count across create/cancel, fleet `current_balance == Σ(net − paid)` over non-written-off invoices across payment+write-off, loyalty points earn/clawback.
- **OCC races** on `Site.version` (rate-plan activation supersede) and `Booking.version` (extend), both serially observable, HTTP 412.
- **Segregation of duties** on incident resolve (resolver ≠ acknowledger), inclusive/exclusive boundary traps everywhere (60/80% occupancy tiers, check-in grace minute, cancel-free 24h, 72h reopen window, credit-limit equality), and a logical clock defaulting to 2026-08-01T00:00:00Z.

## Verification

`scaffold_lint.py` verdict (final run, verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` — 796 calls scanned, 0 violations. Additionally audited: instance-name uniqueness across both files (80 unique), all 31 error codes covered by at least one test instance or stub, no forbidden race vocabulary, every numeric assert pre-computed (e.g., 80%-occupancy Friday quote 7500, per-night-rounding 6000 vs 5999, gross-tiered invoice 540000→10800→529200, 12-night loyalty total 56700 including 3 peak nights).

One fix applied mid-design worth noting downstream: the stall OUT_OF_SERVICE cascade only reassigns bookings whose check-in window has not yet opened — otherwise the check-in stall-ACTIVE precondition would be unreachable.

## Step 3: Copy Shared Files — 2026-08-13T03:56:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T04:18:00.000Z

All contracts pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1389_truck_parking_reservation_network/workspace/PRD.md` (354 lines, ~8,700 words).

**What was generated**

- **§1 Introduction** (2 paragraphs): hours-of-service-driven parking scarcity, dual-pool inventory, enforcement/loyalty/fleet-billing scope.
- **§2 Global Specifications** (9 subsections): RBAC with per-role identity translations (Driver/FleetAccount entity-backed; Anonymous/SiteOperator/NetworkAdmin opaque), verbatim §2.2 response envelope (byte-identical, confirmed by diff), pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup default exactly 2026-08-01T00:00:00Z, never wall-clock, no implicit sweeps), common resource properties (`id` UUID, `created_at`/`updated_at` 3-fractional-digit UTC, `version` init 1), left-to-right nested path validation, the full 21-priority validation pipeline as an explicitly ordered "first failure wins" narrative, integer-cents/round-half-up precision discipline, and both OCC rules (`expected_site_version` on rate-plan activation, `expected_booking_version` on extension, `ERR_STALE_VERSION` 412).
- **§3 Business Logic** (9 subsections): network setup (sites/stalls/rate plans/amenity catalog incl. stall out-of-service reassignment cascade), dynamic pricing + availability + dual-variant forecast, driver standing/strikes/loyalty, booking creation (RESERVED vs WALK_IN, selector, fleet billing gates), the stay lifecycle (check-in, extend, 7-step pinned settlement, no-show/overstay/eviction/cancel, direct payments), amenity capacity and bundling, waitlist offer/accept/expire/withdraw, incidents + derived site posture + pinned ops-run order, and fleet authorization/invoicing/collections. No HTTP methods or paths appear in §3 — endpoints are named via state pairs and role+verb framing.
- **§4**: 4-column table, all 56 endpoints. **§5**: 2-column table, all 32 catalog error IDs.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 82 required, 82 present, 0 missing
- endpoints[].request_body/input: 60 required, 60 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed in ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + occ field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 47 checked across 12 machines, 47 fully expressed, 0 missing
- calculations[]: 15 checked, 15 fully expressed in precise prose (no pseudocode), 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 56 checked, 56 expressed, 0 missing
- entities[].fields[] structured content: 82 checked, 82 reconstructible (defaults, enums, nullability), 0 missing
- sibling-branch symmetry: 6 groups checked (partial/exact payment x2, UPHELD/WAIVED, manual/auto suspend, RESERVED/WALK_IN, forecast variants), 6 symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 696
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Two scaffold inconsistencies preserved faithfully (flagged for downstream consumers, not resolved by invention):** (1) discontinued-product line-adds are bound to `ERR_STALL_NOT_RESERVABLE` by validation §1.4-priority-15 and the §1.6 catalog, but to `ERR_INVALID_STATE` by the AmenityProduct transition side-effect — the PRD carries each statement in its natural subsection (§3.6 and §3.1); (2) `ERR_STALL_OUT_OF_SERVICE` is nominated by the Booking check-in precondition but absent from the §1.6 catalog — the PRD names it in §3.1/§3.5 narrative and correctly omits it from the §5 catalogue.

## Step 5: Generate Unit Tests — 2026-08-13T04:58:00.000Z

Everything passes. The generation is complete.

## Summary

**Task 1389 (truck_parking_reservation_network)** — generated complete test infrastructure from the two design indices, with the PRD as contract.

### Stage 1 — `test_helpers/` (9 files)
- **`types.py`** — 12 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.5) + 17 status/role enums.
- **`api_client.py`** — `ApiClient(GenericApiClient)` with one method per PRD endpoint (46 methods covering all 56 endpoint rows).
- **`api_errors.py`** — 33 `ApiErrorId` values; the 32 catalogued statuses registered via `set_error_http_status_map`. `ERR_STALL_OUT_OF_SERVICE` is deliberately **unmapped** — the PRD names it in §3.1/§3.5 prose but omits it from the §5 catalogue (a flagged inconsistency in the worklog), so only its `error_id` is asserted, never its HTTP status.
- **`assertions.py`** — per-entity structural assertions.
- **`factories.py`**, **`constants.py`** — payload builders and domain thresholds (grace windows, tier pcts, multipliers, invoice tiers, strike weights).
- **`test_users.py`** — opaque roles (Anonymous/SiteOperator/NetworkAdmin) as shared constants; entity-backed roles (Driver/FleetManager) with mandatory `make_driver_headers(entity_id)` / `make_fleet_manager_headers(entity_id)` builders used throughout fixtures.
- **`fixtures.py`** — composite setups: clock control, site+stall builders, driver registration, booking lifecycle (`settle_booking`), fleet pipelines (`setup_fleet_with_active_auth`, `setup_invoiced_fleet_booking` — the full settle→close-billing-period chain), incident workflows, and `setup_offered_waitlist_entry` (book→queue→cancel→OFFERED).

### Stage 2 — `test_suite/` (11 files, 98 tests)
Coverage audit (machine-checked): **all 21 difficulty instances have exactly ≥2 tests** (42 tests), **all 56 non-stub corner instances have ≥1 test** (56 tests). The 4 `excluded_because:` stubs (§errors) were not translated, and their `difficulty_instance` cross-references all resolve. Every test carries a docstring ending in exactly one `Design: Difficulty/...` or `Design: Corner/...` tag copied verbatim from the YAML `name:`.

**PRD-citation audit**: 162 quoted citations, each verified verbatim against `PRD.md` by normalized-substring match. No test walks the scaffold for baseline/smoke/RBAC inventions. No `skip`/`skipif`/`xfail` anywhere; no scaffold references in generated code.

**Two-reader hardening applied**: action-endpoint post-state assertions (fleet status, ops_run_index) go through canonical GET reads; timestamp assertions use prefix matching (fractional-digit formatting isn't pinned for computed datetimes); `per_night_rates` entries assert field-wise rather than exact-dict equality.

Files are grouped by concern: `test_01` site/rate-plan config, `test_02` drivers & RBAC, `test_03` booking windows/pools, `test_04` pricing/settlement/forecast, `test_05` stay lifecycle & sweeps, `test_06` amenities, `test_07` waitlist, `test_08` incidents & posture, `test_09` fleet billing & collections, `test_10` driver standing cascades, `test_11` stall operations.

No instances were skipped — every non-stub instance in both indices passed the PRD-first two-condition filter (verbatim coverage + unique derivability), including the priority-pair tests (§2.7's ordered pipeline pins both pairs explicitly).

## Step 6: Generate Implementation — 2026-08-13T05:06:00.000Z

Two consecutive 98/98 clean runs under `prd-bench-local-run --isolation per-test-server`. The implementation is complete and stable.

## Report

**Delivered**: complete Python + Flask implementation of the Truck Parking Reservation Network API in `/home/ubuntu/github/CodingPRD/tasks/task_1389_truck_parking_reservation_network/workspace/implementation/`:

- `start.sh` — guarded dependency install (`import flask` check), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — entry point, envelope-aware error handlers (400/404/405/500), global request lock, and an `after_request` hook sending `Connection: close`
- `db.py` — empty-on-boot in-memory stores, logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), dashed-UUID minting, timestamp formatters (3-fractional-digit `created_at`/`updated_at`, seconds-precision domain instants)
- `errors.py` — all 32 error IDs with PRD-pinned HTTP statuses (including uncataloged `ERR_STALL_OUT_OF_SERVICE` at 409)
- `util.py` — `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination (default 10/0, clamped 1..100), `Decimal` ROUND_HALF_UP helpers, body shape validators
- `services.py` — dynamic nightly pricing (exact-ratio tier compares, DEGRADED surge cap, peak weekdays), settlement pipeline (pinned order, bundle discount, overstay penalty with ceil-started-hours), stall selector, per-stall waitlist offer scan (tier DESC, created_at ASC), no-show/overstay/escalation/offer-expiry ops-run sweeps in pinned order, driver-suspension and fleet-overdue/reactivation cascades, loyalty earn/clawback
- `routes/` — 9 blueprints covering all 56 endpoints with the PRD §2.7 validation priority order (auth → ownership → existence → shape → state → OCC → ESCALATED → windows → timing → conflicts → standing → authorization → fleet → fit → capacity → segregation → credit → spend cap → payment discipline)

**Test results**: 98/98 passed on two consecutive full runs under `--isolation per-test-server` (~120s each), plus all earlier smoke suites.

**Key findings during validation**:
1. The harness's `is_valid_uuid` requires dashed UUIDs — `uuid4().hex` fails every entity assertion; fixed to `str(uuid4())`.
2. The runner's start command must be in `cd <dir> && <cmd>` form — `executor._absolutize_start_command` only rewrites that shape, and the per-test restart re-resolves relative dirs against `test_suite/`. My first full run used `--start-command "bash workspace/implementation/start.sh"` and all 98 tests timed out in setup; the correct invocation is `--start-command "cd workspace/implementation && bash start.sh"`.
3. The test client uses a pooled `requests.Session`; with per-test SIGKILL restarts, stale keep-alive connections produced intermittent `RemoteDisconnected` failures. The `Connection: close` response header in `app.py` eliminated that flake class (failures before hardening: 96/98 and 94/98 with varying load-induced flakes; after: 98/98 twice).

One spec ambiguity resolved by 2-of-3 vote: adding a line against a discontinued/foreign amenity product returns `ERR_STALL_NOT_RESERVABLE` (PRD §3.6 + scaffold validation 15 + error catalog) rather than `ERR_INVALID_STATE` (PRD §3.1).

## Step 7: 8-Round Parallel Stability Sweep — 2026-08-13T06:25:00.000Z

**Iteration 1 (8 concurrent rounds)**: union of 3 flaky tests (`test_noshow_sweep_strict_greater_than_boundary` r1/3/6, `test_occ_booking_extend_stale_version` r2/4/7, `test_ops_run_epoch_idempotent_second_sweep` r5) — every failure was transport-level (`ConnectionResetError` / `RemoteDisconnected` mid-test, or "could not be restarted" when a boot exceeded the runner's 15s per-test restart poll), all inside one ~20s host-wide contention spike at 05:31 (this host runs several sibling prd-bench pipelines concurrently; the port registry showed 39 holders). No assertion ever failed; STEP 1/2 audit confirmed all three tests assert verbatim PRD rules with faithful setups, so nothing was deleted.

**Diagnosis**: the test client (`test_helpers/api_client.py`) used a plain `requests.Session` with `Retry(total=0)` — the first transport error failed the test. Server-side, Werkzeug 3.1.8's dev server unconditionally sends `Connection: close` and closes every connection (hardcoded in `WSGIRequestHandler.run_wsgi`); per-test SIGKILL restarts plus 8× concurrency turn that into connect/reset races.

**Fixes**:
- `test_helpers/api_client.py` — mount a retrying `HTTPAdapter` on the shared session (`Retry(total=4, connect=4, read=4, backoff_factor=0.05, allowed_methods=None, status=0)`). Only transport errors are retried (HTTP 4xx/5xx untouched, no assertion weakened); safe for mutating endpoints because a transport-failed request never reached a handler (verified empirically: kill+restart mid-session absorbed in 0.31s; dead server fails bounded in 0.70s).
- `workspace/implementation/start.sh` — dependency guard now uses `importlib.util.find_spec('flask')` (22ms) instead of a full `import flask` (279ms) on every per-test reboot.
- `workspace/implementation/app.py` — comment corrected (removed the redundant `Connection: close` override; documented that transport resilience lives in the test client).

**Verification**: iteration 2 clean 8×98/98 (light contention). A 3× synthetic-contention harness (8 authoritative + 16 load rounds, host load 25) reproduced boot-timeouts in iteration 3, then ran fully clean in iteration 5 (24/24 rounds 98/98; all 2376 captured server exits were boundary SIGKILLs, zero anomalous deaths). Iteration 4's three residual failures were a synchronized external process-kill event at 06:05:56 across lockstep rounds (foreign pipeline activity; server logs clean, no tracebacks) — a host-level event no artifact can survive. Final protocol sweep + confirmation sweep on the exact final artifacts: 8×98/98 each.

## Step 8: Finalize PRD — 2026-08-13T06:30:00.000Z

PRD_FINALIZED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1389_truck_parking_reservation_network/workspace/PRD_FINALIZED.md` as an exact, byte-identical copy of PRD.md (diff confirms no differences).

**Line counts and delta**: PRD.md 353 lines; PRD_FINALIZED.md 353 lines; 0% delta.

**Changes**: none. Zero PRD edits are warranted.

**Justification** — every Step 7 diff item was verified against the actual files and none is a PRD silence or PRD/impl mismatch:

1. `test_helpers/api_client.py` retry adapter — confirmed at lines 7-43: mounts `Retry(total=4, connect=4, read=4, status=0, allowed_methods=None, raise_on_status=False)` on the shared session. This is test-harness transport resilience only; it retries only transport-level failures (connection reset/EOF before a response), never touches HTTP status semantics, and lives entirely outside the implementation. The PRD specifies API request/response behavior, not the test client's TCP retry policy — nothing to pin.
2. `workspace/implementation/start.sh` dependency-guard speedup — confirmed at lines 9-11: `importlib.util.find_spec('flask')` guard instead of a full `import flask`. Pure boot-time optimization; no API behavior change. The build contract (start.sh, PORT binding, foreground) belongs to INSTRUCTION.md, not PRD.md, and is unchanged.
3. `workspace/implementation/app.py` comment-only correction — confirmed at lines 33-43: a comment block explaining that Werkzeug's dev server closes every connection and that transport resilience lives in the test client. No code was altered.

A grep of PRD.md for `retry|connection|keep-alive|start.sh|pip|find_spec|werkzeug|transport|TCP|SIGKILL|restart|dependency` found only two domain-meaning hits of "restart" (hours-of-service weekly restart cycles, lines 5 and 156) — unrelated to any Step 7 site. The PRD contains no transport/boot-level prose that these fixes could contradict or leave under-determined.

**Per-edit pre-edit search log**: no edits were made, so (a)/(b)/(c) are empty for all edits. The zero-edit conclusion itself rests on the file reads and grep enumerated above, which confirmed each Step 7 item is infrastructure-only with no behavioral surface the PRD could pin.

## Step 9: Complete PRD — 2026-08-13T06:52:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1389_truck_parking_reservation_network/workspace/PRD_COMPLETED.md`.

**Size**: PRD_FINALIZED.md 353 lines / 61,110 chars → PRD_COMPLETED.md 354 lines / 67,016 chars (+1 line, +5,906 chars). 28 in-paragraph edits; no new sections.

**Counts**: 24 ambiguity-pins, 4 mismatch-revisions.

**Mismatch-revisions**
- §3.1 (amenity catalog) — revise — mismatch — adding a line against a discontinued product is `ERR_STALL_NOT_RESERVABLE`, not `ERR_INVALID_STATE` — implementation/routes/bookings.py:419-422
- §2.7 step 4 — revise — mismatch — on creation endpoints (booking, waitlist entry, driver authorization) body-shape validation runs *before* payload ownership and body-reference existence; `force` shape precedes check-out's role branch — implementation/routes/bookings.py:55-89,281-292; routes/waitlist.py:31-59; routes/auths.py:39-48
- §4 preamble — revise — mismatch — posting a payment persists no separate payment record; the 201 response carries the updated booking/invoice — implementation/routes/bookings.py:385; routes/fleets.py:257
- §5 error catalogue — revise — mismatch — added missing `ERR_STALL_OUT_OF_SERVICE` (409) row; it was named in §3.1/§3.5 prose but absent from the catalogue — implementation/errors.py:113-114

**Ambiguity-pins**
- §2.3 — insert — non-integer limit/offset ignored for defaults; out-of-range clamped not rejected; `has_more` = offset+returned < total_count; `created_at` ties broken by insertion order; filters match by exact equality (no match → empty page) — implementation/util.py:51-74
- §2.4 — insert — entity timestamps read the logical clock, only `api_request_timestamp` is wall-clock; unparseable `to_iso8601` → `ERR_VALIDATION`; offset-less values read as UTC — implementation/db.py:64-75; util.py:18-20; routes/clock.py:20
- §2.5 — insert — sweeps/cascades/consolidations process resources `created_at`-ascending (insertion-order tie-break), invoice `booking_ids` in that order; non-common stamped instants render seconds-precision (3 fractional digits only when sub-second); date fields render as calendar dates — implementation/services.py (all sweeps sort `(created_at, _seq)`); db.py:88-94
- §2.6 — insert — undefined paths and unsupported methods → `ERR_NOT_FOUND` 404 — implementation/app.py:49-55
- §2.7 step 3 — insert — body-referenced ids (`driver_id`, `site_id`, `fleet_account_id`) must exist else `ERR_NOT_FOUND` — implementation/routes/bookings.py:79-89
- §2.7 step 4 — insert — payment amounts must be positive integers (`ERR_VALIDATION`) — implementation/routes/bookings.py:368-369; routes/fleets.py:235-236
- §2.7 step 9 — insert — after check-in timing, assigned stall not `ACTIVE` → `ERR_STALL_OUT_OF_SERVICE`; waitlist accept past `offer_expires_at` → `ERR_OFFER_EXPIRED` at the same pipeline position — implementation/routes/bookings.py:267-269; routes/waitlist.py:160-164
- §2.9 — insert — omitting a required version field is `ERR_VALIDATION`; only present-but-mismatched is `ERR_STALE_VERSION` — implementation/routes/site_children.py:186-188; routes/bookings.py:317
- §3.1 (sites) — insert — site PATCH bumps `version` once per call even with no fields; null-valued fields treated as absent — implementation/routes/sites.py:76-94
- §3.1 (stalls) — insert — `is_reservable` filter accepts `true`/`false` case-insensitively, other values match nothing — implementation/routes/site_children.py:32-40
- §3.1 (stalls) — insert — PATCH without `status` is a no-op (no version bump); PATCH naming current status → `ERR_INVALID_STATE` — implementation/routes/site_children.py:100-104
- §3.1 (reassignment) — insert — outstanding waitlist offers do not exclude replacement candidates — implementation/routes/site_children.py:117-119 (respect_offers defaults False)
- §3.1 (rate plans) — insert — transitions to `DRAFT`/`SUPERSEDED` → `ERR_INVALID_STATE`; `peak_days` is `MON`–`SUN` weekday codes, default `["FRI","SAT"]` — implementation/routes/site_children.py:199-200,143-145
- §3.1 (amenity products) — insert — duplicate code at creation → `ERR_VALIDATION`; explicit null `nightly_capacity` clears the cap; version advances only on actual change; `ACTIVE`→`ACTIVE` is a no-op; re-discontinue → `ERR_INVALID_STATE` — implementation/routes/site_children.py:236-238,272-290
- §3.2 (availability) — insert — omitted `window_end` = today's 11:00Z turnover if after start else tomorrow's; unparseable window params → `ERR_WINDOW_INVALID`; only `ACTIVE` stalls counted; outstanding offers don't reduce free counts — implementation/routes/sites.py:103-139
- §3.2 (forecast) — insert — missing `date` → `ERR_VALIDATION`, unparseable → `ERR_WINDOW_INVALID`; zero `ACTIVE` stalls → both percentages 0.0 — implementation/routes/sites.py:148-183
- §3.5 (cancel) — insert — free cancellation leaves `final_total_cents` null (only fee-carrying and system cancellations set it) — implementation/routes/bookings.py:236-240
- §3.5 (extension) — insert — `quoted_total_cents` recomputed over all pinned nights with loyalty discount re-applied at the driver's *current* tier — implementation/routes/bookings.py:346-354
- §3.5 (overstay escalation) — insert — auto-incident carries the fixed description "Auto-escalated overstay" — implementation/services.py:516
- §3.5 (eviction) — insert — SiteOperator check-out without `force` → `ERR_FORBIDDEN`; force on non-`OVERSTAY` → `ERR_INVALID_STATE`; Driver passing `force` true → `ERR_FORBIDDEN` — implementation/routes/bookings.py:284-294
- §3.6 — insert — fulfillment PATCH body must carry `status` equal to `FULFILLED`; any other target → `ERR_INVALID_STATE` — implementation/routes/bookings.py:487-491
- §3.7 (offer scan) — insert — scan is a no-op unless the freed stall is `ACTIVE` and reservable; candidate window must also be free of overlapping `OFFERED` pins; exact tier+`created_at` ties fall back to insertion order (entry `id` still never used) — implementation/services.py:290-317
- §3.7 (accept) — insert — the response carries the promoted waitlist entry, not the new booking — implementation/routes/waitlist.py:227-229
- §3.8 — insert — a Driver-supplied `reporter_driver_id` differing from `X-User-ID` → `ERR_FORBIDDEN` — implementation/routes/incidents.py:39-43
- §3.9 (authorizations) — insert — request not gated on fleet status; duplicate (driver, fleet) authorizations permitted, each minting a fresh `PENDING` — implementation/routes/auths.py:34-56
- §3.9 (invoicing) — insert — malformed `period` → `ERR_VALIDATION`; close-billing-period permitted regardless of fleet status — implementation/routes/fleets.py:105-119
- §3.9 (collections) — insert — fleet ops-run invocable whatever the fleet's status — implementation/routes/fleets.py:96-102
- §3.9 (close) — insert — re-closing a `CLOSED` fleet → `ERR_INVALID_STATE`; closure also system-cancels not-yet-open `BOOKED` fleet-billed bookings fee-free — implementation/routes/fleets.py:70-87

Method note: every endpoint, state transition, formula, and error path in `implementation/` (app/auth/db/domain/errors/util/services + 9 route modules) was walked line-by-line against the PRD; the pipeline order in §2.7 was verified against actual check ordering in each handler. Tests were not consulted as authority.
