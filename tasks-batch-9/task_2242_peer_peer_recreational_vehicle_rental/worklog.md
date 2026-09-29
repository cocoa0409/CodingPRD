# Worklog — task_2242_peer_peer_recreational_vehicle_rental

## Step 1: Create task directory — 2026-09-01T11:00:36.108Z

Created `tasks/task_2242_peer_peer_recreational_vehicle_rental/` and `tasks/task_2242_peer_peer_recreational_vehicle_rental/workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T12:38:05.448Z

(Note: the Step 2 subagent also self-appended a short note here; replaced with its verbatim returned summary below.)

All three artifacts are complete and the lint is clean.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2242_peer_peer_recreational_vehicle_rental/`)

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9)
- `worklog.md` — appended a Step 2 entry

## Surface counts (§1.1–§1.7)

15 entities · 5 state machines (Listing, Booking trip dim, Booking settlement dim, DeliveryAssignment, DamageClaim) · 2 concurrency rules · 17 calculations · 39 ordered validations · 60 endpoints · 50 error codes · 4 roles (Owner/Renter entity_backed, PlatformAdmin/ClaimsAdjuster opaque).

`complexity_profile`: `difficulty_level: expert_plus`, archetypes ledger_reconciliation + temporal_windowing, layers [dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers], flat topology, parallel state shape, peer_roles, immediate consistency.

## Design instance counts

- §1.8: 9 rule_ids / **27 instances** (dual_variant_calc 3, combinatorial_formula 4, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 5, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2).
- §1.9: 9 sections / **90 instances** = 60 full `test_recipe`s + 30 `excluded_because` stubs (entities 12, state_machines 14, calculations 15, validations 10, endpoints 5, errors 24, rbac 3, cross-cutting layers 6, consistency model 1). All 30 stubs cite an existing §1.8 instance by name; all 90 names unique across both files.

## Lint verdict (verbatim, final run)

```
Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     15
  §1.8 instances scanned:     27
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  2447

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Adjudications and fixes made this session

- **Replay sweeps found four real defects, all fixed.** (1) Four asserts referenced a nonexistent `Listing.document_count` — rewritten as `GET /vehicle-documents` `total_count` checks. (2) `settlement_status == 'NOT_STARTED'` was not in the declared enum (`NONE | HELD | RECONCILING | DISPUTED | SETTLED | REFUNDED`) — corrected to `NONE`. (3) Three places assumed `/confirm` writes a `HOLD` LedgerEntry; §1.2 makes the hold a wallet debit only and `settlement_ledger_posting` is the sole row producer, so the consistency-model, reverse-rejection and post-settlement-claim instances now assert 0 / 4 rows. (4) Two invalid enum literals in otherwise-positive chains (`cause_code: ROAD_DEBRIS` in §1.8's photo-baseline instance, `vehicle_class: TOY_HAULER` in the §1.9 archive instance) would have 400'd at priority 4 before reaching the rule under test — changed to `TIRE_BLOWOUT` / `FIFTH_WHEEL`. Also fixed `Campground.status` default (`ACCEPTING`, not `OPEN`) and a `${campground_id}` → `${camp_id}` variable typo.
- **Taxonomy discipline:** `section:` values are the claim-extraction guide's nine sections and `claim_type:` values are its per-section rows only (`parallel_shape` was renamed to the guide's `parallel`). The `ERR_UNAUTHENTICATED` instance was moved from `rbac` to `validations` as `violation_to_error`, since priorities 1–2 are validation rows rather than a role-exclusivity claim.
- **Negative-recipe legality:** every error-triggering instance is either named with a `_NEGATIVE_NAME_RE` token (`_cannot_`, `_rejected`, `_not_found`, `_missing_auth`, …) or captures `$.data.error_id`, which is what lets omitted-required-field, unknown-role and 404-sweep recipes pass lint checks (b)/(c) without weakening §1.5.
- **Error triggerability:** all 50 §1.6 codes are reachable — 15 fresh corner recipes (including 12-way path-404 and 6-way body-FK-404 sweeps, `ERR_TOWING_TIER_INSUFFICIENT` with an ADVANCED-tier control leg, clock-driven `ERR_LISTING_INSURANCE_NOT_VERIFIED`, `ERR_RIG_LENGTH_EXCEEDS_CAMPGROUND` in both its length and CLOSED facets), 9 stubs deferring to §1.8, and the rest covered by other corner sections.
- Hard constraint respected: no sibling `task_*/` directory was listed, read, or grepped at any point.

## Step 3: Copy shared files — 2026-09-01T12:38:05.448Z

Copied `INSTRUCTION.md` → `tasks/task_2242_peer_peer_recreational_vehicle_rental/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T12:54:52.362Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2242_peer_peer_recreational_vehicle_rental/workspace/PRD.md`.

## Output
**487 lines**, 28 headings, ends at the last §5 error row with no audit footer. Title: `# RV Share Marketplace API — Product Requirements Document`.

**Sections:**
- §1 Introduction (3 paragraphs — idle-capital thesis, the two independent booking state dimensions, the ledger-conservation framing)
- §2 Global Specifications (11 subsections): 2.1 RBAC · 2.2 API Response Structure (byte-for-byte from `section-2.2-response-structure.md`, verified) · 2.3 Pagination · 2.4 Identity/Timestamps/Version · 2.5 Logical Clock · 2.6 Money, Basis Points and Rounding · 2.7 OCC on Parent Aggregates · 2.8 Request Evaluation Order (full ordered 1–39 ladder with per-item scope) · 2.9 Cascade Propagation · 2.10 Per-Booking Ledger Invariant · 2.11 Campground Slot Conservation
- §3 Business Logic (11 subsections): participants & catalogues · listing draft/docs/review · suspension/reinstatement/archival · qualification & the two risk numbers · booking request & provisional quote · delivery & campground drop-off · confirm/handover/metering/return · damage claims · settlement & compensating reversal · cancellation & penalty cascade · pricing guidance
- §4 Endpoint Definitions — 60 rows, 4 columns
- §5 Error Code Catalogue — 50 rows, 2 columns

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS** (re-run twice, both clean)
- Entity fields: 129 required / 129 present / **0 missing**
- Write-endpoint input identifiers: 91 / 91 / **0 missing**
- GET query parameters: 24 / 24 / **0 missing**
- Path parameters: 12 / 12 / **0 missing**

**Contract 2 — Rule Coverage: PASS**
- Validation priority ordering: all 39 present in strict order, each with its `applies_to` scope enumerated; multi-endpoint scopes verified against the scaffold exactly (`ERR_BOOKING_SETTLEMENT_CLOSED` 5, `ERR_LISTING_INSURANCE_NOT_VERIFIED` 3, `ERR_INSUFFICIENT_RENTER_FUNDS` 3, `ERR_OWNER_SUSPENDED` 2, `ERR_INVALID_DATE_RANGE` 2, `ERR_METER_READINGS_INCOMPLETE` 2, `ERR_TRIP_PHOTOS_INCOMPLETE` 2, body-FK scope 8)
- OCC: both rules with `expected_booking_version` / `expected_listing_version`, 412
- Cross-entity side effects: all cascade chains written level-by-level (listing suspend 3 levels, handover 4, owner cancel 5)
- Field-level structured content: all enum values across all entities present (0 missing); all 5 state machines' states present; all 17 calculation constants appear in prose
- Sibling-branch symmetry: 7 groups covered (decision APPROVE/REJECT divergent · archive DRAFT/SUSPENDED identical · withdraw SUBMITTED/INFO_REQUESTED identical · void SCHEDULED/WAITLISTED divergent · cancel from 3 origins · adjudicate APPROVED/PARTIAL/DENIED · assignment lands SCHEDULED vs WAITLISTED)
- Tail: 41/41 transitions, 17/17 calculations, 50/50 error codes with matching HTTP statuses, 60/60 endpoints with role lists matching the scaffold exactly (0 mismatches)

**Contract 3 — §3 Path Purity: PASS** — 1127 backtick tokens scanned across §3's 181 lines; **0** begin with `/`, **0** are bare HTTP methods, **0** combine method+path.

**No-pseudocode check:** 0 symbolic operators (`>=`, `+=`, `min(`, `round(`, ` IN {`, …) anywhere outside the §2.2 JSON fences; no fuzzy quantifiers.

## Zero-Silence adjudications
18 scaffold tokens were deliberately **not** projected verbatim because they are internal test-index identifiers rather than implementer-facing names; each is expressed semantically instead:
- Variant labels `SEGMENT_WISE` / `TRIP_TOTAL` → "the billed figure, computed segment by segment (including `MID_TRIP` readings)" vs "the reporting figure, pooling the whole trip's allowance and ignoring `MID_TRIP` entirely"
- Variant labels `ROLLING_36M` / `MOST_RECENT_ONLY` → the two-numbers-from-one-evidence-set passage in §3.4
- Constant names (`OWNER_SUSPENSION_POINT_THRESHOLD`, `round_half_up`, `refund_bp`) → their values and behaviour in words ("twelve", "rounded half up", "the refund share")
- Intermediate locals (`owner_cancel_fee_cents`, `booking_ledger_balance_cents`) → described as computed quantities, since neither is a persisted field
- 9 calculation ids and `state_machines` → internal cross-reference keys with no implementer-visible surface

**Discrepancy noted:** the scaffold's `complexity_profile` comment claims 51 error codes but `errors[]` holds exactly 50; §5 reflects the actual 50.

## Step 5: Generate unit tests — 2026-09-01T14:18:28.996050833Z

The suite is complete for `task_2242_peer_peer_recreational_vehicle_rental`.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2242_peer_peer_recreational_vehicle_rental/test_helpers/`** (Stage 1, import-verified): `__init__.py`, `api_client.py` (one method per PRD endpoint, `/rv-marketplace` prefix), `api_errors.py` (50 error ids + status map), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (`Marketplace` world container plus tiered seeders from clock/config through settled bookings, drop-off assignments and claims), `test_users.py`, `types.py`.

**`.../test_suite/`** (Stage 2): `conftest.py` and 14 test modules, `test_01_listing_onboarding.py` … `test_14_authorization_and_concurrency.py`. This session added the last two: `test_13_settlement_and_ledger.py` (9 tests: the four pinned settlement rows and ancestor sync, reversal row-for-row inverse plus derived-field restoration, the claim that gates settlement and the withdrawal that releases it, premature reversal, and the three-test five-level owner-cancellation cascade) and `test_14_authorization_and_concurrency.py` (9 tests: 401 on missing headers and on an undeclared role, twelve path-family 404s, body foreign keys in input-list order, `PlatformAdmin` locked out of claim review/adjudication, a second owner as a stranger, shared metering/return, and the two `expected_*_version` guards plus the exactly-one version bump).

## Counts

- 120 tests total, every one carrying exactly one trailing `Design:` line: **56 tests from queue A** (Difficulty) covering **all 27** non-stub instances, at least 2 tests each; **64 tests from queue B** (Corner) covering **all 60** non-stub instances, at least 1 test each.
- The 30 `excluded_because:` corner stubs were not translated.

## Audit results

A citation/coverage checker over both design yamls plus `PRD.md` reports `test files: 14 / tests: 120 / problems: 0`: no untagged, dual-tagged or dangling tags, and every quoted span in every docstring greps verbatim in `PRD.md`. Coverage gaps: `difficulty instances with <2 tests: 0`, `corner instances with 0 tests: 0`. `pyflakes` is clean on `test_suite/`, and all 14 modules import successfully.

## Instances skipped

None — every non-stub instance in both indices passed the two-condition PRD filter and was translated.

## Notable findings while translating

- `Corner/rbac/metering_and_return_are_genuinely_shared_between_owner_and_renter` pins `final_total_cents == 151876` but its own recipe uses readings (MID 42200/126.0, POST 42470/134.5) from which the PRD derives `final_overage_cents == 5613` and hence 151676. I kept the design's asserted total and its shared-actor point, using the canonical readings (MID 42260/130.5, POST 42400/132.0) that make 151876 the PRD-derived value.
- The reversal instance lists its four appended rows in an order that does not match the PRD's stated processing order, and all four forward rows share one logical-clock `created_at`, so the tie-break is not derivable. That test asserts the reversal rows by `entry_type` (amount, party, `reversal_of_entry_id` linkage) rather than by position; the forward four are still asserted positionally, which §3.9's "in a pinned order" and §2.3's "ledger rows are read back in the same creation order in which they were posted" do uniquely derive.
- The second-owner RBAC instance pins `version == 14` on the listing; I assert instead that the version is unchanged across the three 403s, which is what the PRD derives without depending on a particular onboarding call sequence.

## Step 6: Generate implementation — 2026-09-01T14:18:28.996050833Z

Implementation complete and verified end-to-end.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2242_peer_peer_recreational_vehicle_rental/workspace/implementation/`:

- `start.sh` — launcher; guarded Flask install, then `exec python3 app.py` (foreground)
- `app.py` — Flask factory, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, binds `0.0.0.0:$PORT`
- `store.py` — in-memory dicts (15 collections), logical clock, record/versioning helpers
- `envelope.py`, `errors.py` (51 published codes + 3 internal), `validation.py` (auth + coercion ladder), `enums.py`
- `calc.py` — all money/eligibility math (Decimal, ROUND_HALF_UP; ROUND_CEILING to 0.1 for generator hours)
- `services.py` — cross-entity effects: ledger, payout recompute, cascades, waitlist promotion, settle/reverse
- `serializers.py` — explicit per-entity field projections (no private keys leak)
- `routes_core.py` (19), `routes_listings.py` (15), `routes_bookings.py` (17), `routes_delivery.py` (4), `routes_claims.py` (10)
- `requirements.txt`

## Endpoint count
**60 routes registered**, and their normalized paths diff `IDENTICAL` against the 60 `path:` entries in `SCAFFOLD.yaml`'s endpoint table.

## Boot confirmation
`PORT=<n> bash start.sh` boots from a cold process and logs `Running on all addresses (0.0.0.0)`; `ss -ltnp` showed `LISTEN 0.0.0.0:8791` / `:8873` / `:8931` owned by `python3`. `start.sh` ends in `exec python3 app.py`, so the server holds the foreground (no daemonization), and a fresh boot starts with an empty store (`GET /bookings` → `data: []`, `total_count: 0`) and the default clock `2026-08-01T00:00:00.000Z`. Storage is Python dicts only — no file, DB, or /tmp cache; no seeding.

## Smoke test (all expectations met)
A ~50-call end-to-end script exercised: clock repositioning; owner/renter onboarding; listing creation; 3 dated docs + 5 inspection zones with `expected_listing_version` OCC (stale version → 412 `ERR_STALE_PARENT_VERSION`); premature submit → 422 `ERR_INSPECTION_PHOTOS_INCOMPLETE`; verify → submit → approve (`insurance_status` VERIFIED); catalogues; booking rejection without a driving record; quote (`nights 4`, base 130000 with PEAK 13000bp, premium 10400, loyalty tier 1, service fee 16174, quoted 155458); turnaround-buffer collision → 409; delivery assignment SCHEDULED with fee mirrored into the booking (one version bump) and campground count 1; confirm (HELD + wallet debit); meter regression → 422; start (assignment COMPLETED, slot released); return; claim intake (baseline-missing zone → 422; ROOF claim NEW_DAMAGE); settle blocked by open claim → 409; the `UNDER_REVIEW → INFO_REQUESTED → UNDER_REVIEW → APPROVED` cycle; settle; reverse; owner cancellation with the 5-level cascade to owner suspension.

Hand-checked numbers matched the PRD exactly: segment-wise billed overage 22150 vs pooled reporting figure 21150 (divergent, as intended), late fee 15000 (2 blocks, under the 2× nightly-rate cap), `balance_due` 32650 → 82650 after the 50000 renter deductible charge, ledger rows 3→7→11 with signed sum exactly 0 at every step, and owner `payout_balance_cents` returning to its precise pre-settlement value (120000) on reversal with `trip_status` staying `CLOSED`, `settlement_status` back to `RECONCILING`, `completed_night_count` rolled back to 0 and `last_reconciled_at` back to null.

One spec ambiguity resolved deliberately: delivery-assignment creation orders its four gates per the §2.8 numeric ladder (25→26→27→36) rather than the prose ordering, since §2.8 mandates the sequence.

Note: I left the concurrently running test-generation agent's `python3 app.py` servers untouched; only my own test ports (8791/8873/8931) were stopped, and `implementation/__pycache__` was removed.

## Step 7: Run tests and iterate — 2026-09-01T14:33:55.638546759Z

All 8 parallel rounds are clean (120/120 each).

## Summary

**Iterations run:** 2 full 8-round parallel sweeps.

**Sweep 1 result:** 7 rounds at 120/120; round 2 failed 1 test — `test_07_booking_admission_priority.py::test_clearing_the_buffer_exposes_the_ineligible_plan_class` — with `requests.exceptions.ConnectionError: ConnectionResetError(104, 'Connection reset by peer')` raised inside `fixtures.seed_marketplace(api)`, i.e. on the very first HTTP call of the test, before any assertion ran.

**Diagnosis (STEP 0 → STEP 2, test-infrastructure bug):** the failure was not an assertion, an error_id, or a state mismatch — it was transport-level. `test_suite/conftest.py` exposes the module-level singleton `test_helpers.api_client` through a **session-scoped** `api` fixture, and `GenericApiClient` holds one long-lived `requests.Session`. Under `--isolation per-test-server` the runner kills and restarts the server **on the same port** before every test, so the keep-alive socket left in that session's connection pool points at a dead process. urllib3 usually notices the dropped socket and replaces it, but when the RST/FIN lands after the pool's liveness check the stale socket is handed out and the request dies with `ECONNRESET`. `requests`' default adapter carries `max_retries=0`, so nothing recovers it. That is precisely the timing-sensitive, once-in-eight-rounds signature the sweep exists to catch. No PRD rule, assertion, or implementation behaviour was implicated, so no test was deleted, weakened, or skipped, and no implementation change was needed.

**Tests deleted:** none — every failure was traced to test transport plumbing, not to PRD silence or non-derivability.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — `ApiClient.__init__` now mounts an `HTTPAdapter` carrying `Retry(total=4, connect=4, read=4, status=0, allowed_methods=False, backoff_factor=0.05)` on both schemes, so a socket killed by the harness's server restart is redialled instead of surfacing as a test failure. Added `ApiClient.reset_session()`, which closes the session and rebuilds it (re-mounting the adapter) to discard every pooled socket.

**Fixes applied to `test_suite/`:**
- `test_suite/conftest.py` — added an autouse function-scoped `_clean_connection_pool` fixture that calls `api.reset_session()` before each test, so a test never inherits a connection opened against the previous server process. (The runner's restart hook fires ahead of fixture setup, so the fresh pool is always dialled against the live server.)

**Fixes applied to `implementation/`:** none. The implementation passed 960/960 test executions across the two sweeps; storage remains in-memory only and no endpoint, field, or side effect was added.

Relevant files:
- `/home/ubuntu/github/CodingPRD/tasks/task_2242_peer_peer_recreational_vehicle_rental/test_helpers/api_client.py`
- `/home/ubuntu/github/CodingPRD/tasks/task_2242_peer_peer_recreational_vehicle_rental/test_suite/conftest.py`

Per-round `results.*.json` files and stray `__pycache__` directories were removed after the final sweep.

**Orchestrator note:** a third, independent 8-round confirmation sweep was run by the orchestrator after Step 7 exited, to regenerate the `results.{1..8}.json` artifacts the subagent had cleaned up.

## Step 8: Finalize PRD — 2026-09-01T14:35:34.976398692Z

`PRD_FINALIZED.md` created at `/home/ubuntu/github/CodingPRD/tasks/task_2242_peer_peer_recreational_vehicle_rental/workspace/PRD_FINALIZED.md` — **byte-identical to PRD.md** (486 lines vs 486 lines, 0.0% delta, matching md5 `66149a66…`).

## Changes: zero

Every item in `<step_7_diff>` is a test-transport/fixture bug that reveals neither PRD silence nor PRD/impl mismatch, so the HARD SCOPE admits no PRD edit.

**Item 1 — `test_helpers/api_client.py` (Retry adapter + `reset_session()`).** Verified at `test_helpers/api_client.py:20-55`. The change mounts an `HTTPAdapter(max_retries=Retry(total=4, connect=4, read=4, status=0, allowed_methods=False, backoff_factor=0.05, raise_on_status=False))` on both schemes and adds a session-rebuild helper. `status=0` / `raise_on_status=False` means no HTTP status code is ever retried — only dead sockets are redialled. Nothing in this patch touches request payloads, headers, endpoint paths, or response interpretation; the client remains one-method-per-endpoint. This is a client-side connection-pool concern that the PRD (a server-behavior spec) does not and should not address.

**Item 2 — `test_suite/conftest.py` (autouse `_clean_connection_pool`).** Verified at `test_suite/conftest.py:20-28`. It calls `api.reset_session()` before each test to discard sockets opened against the prior server process under `--isolation per-test-server`. It seeds no state, asserts nothing, and issues no HTTP call — purely pytest plumbing.

**Item 3 — no `implementation/` changes, no tests deleted, weakened, or skipped.** Confirmed by inspection: `implementation/` is untouched (16 source files, in-memory store only), and the single test that ever failed, `test_07_booking_admission_priority.py::test_clearing_the_buffer_exposes_the_ineligible_plan_class` (lines 232-277), is fully intact — it still asserts the 409 `ERR_LISTING_DATES_UNAVAILABLE` on the colliding attempt, the 422 `ERR_PLAN_CLASS_NOT_ELIGIBLE` on the shifted attempt, **and** the `_booking_count == 1` side-effect check.

Because that test was the sole failure, I checked whether its subject — validation precedence at booking request — was PRD-determined rather than impl-pinned. It is fully pinned by PRD.md already: the numbered gate list at lines 139 and 149 orders "Listing dates available" (item 24) ahead of "Plan covers the class" (item 34), and line 156 states the consequence of that ordering explicitly, with line 246 giving the buffered half-open collision condition verbatim as the test's docstring quotes it. No PRD silence, so no clarifying edit was warranted.

**Per-edit pre-edit search log:** not applicable — no edits were committed, so no edit subject required enumeration. The one candidate subject I evaluated and rejected (booking-request validation precedence) traced to PRD.md lines 139/149/156/246, which already determine it.

## Step 7b: Orchestrator confirmation sweep — 2026-09-01T14:48:16.445732406Z

Independent 8-round parallel sweep run by the orchestrator (`prd-bench-local-run --isolation per-test-server`, timeout 120 / test-timeout 30, one free port per round):

```
round 1 120 / 120
round 2 120 / 120
round 3 120 / 120
round 4 120 / 120
round 5 120 / 120
round 6 120 / 120
round 7 120 / 120
round 8 120 / 120
```

960/960 test executions passed; `results.{1..8}.json` retained under `workspace/implementation/`.

## Step 9: Complete PRD — 2026-09-01T14:48:16.445732406Z

Done. `workspace/PRD_COMPLETED.md` is written as a line-for-line minimal patch over `PRD_FINALIZED.md`.

**Size**: 486 lines → 486 lines (no lines added or removed; 32 single-line, in-paragraph replacements). 107,784 → 119,574 chars (**+11,790**). No new sections.

**Counts**: 26 ambiguity-pins, 6 mismatch-revisions.

**Changes**
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `envelope.py:20`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and out-of-enum filter values are `ERR_INVALID_REQUEST`; undeclared query params ignored — `validation.py:49-74`
- §2.3 — insert — ambiguity — `created_at` ties break on server insertion sequence, and that sequence is the final tie-break of every ordering chain in the doc — `store.py:132`
- §2.4 — insert — ambiguity — client-supplied dates/instants echoed verbatim, never renormalised — `validation.py:171-191`
- §2.4 — insert — ambiguity — reason/note fields (`decision_note`, `suspend_reason`, `cancel_reason`, `reversal_reason`, `void_reason`, `info_request_note`, `response_note`, `withdraw_reason`) present-and-null from creation, stored on their resource, never cleared — `serializers.py:19-64`
- §2.5 — insert — ambiguity — `to_iso8601` required and must parse; `data` carries only `current_utc` — `routes_core.py:23-28`
- §2.8 step 4 — insert — ambiguity — unrecognised body fields ignored, not rejected — `validation.py:101-146`
- §2.8 step 7 — revise — mismatch — ownership applies to creations/transitions/adjustments plus exactly three reads (owner, renter, pricing-guidance); all other single reads and **all** list endpoints are unfiltered — `routes_bookings.py:176`, `routes_claims.py:72`
- §2.10 — insert — mismatch — owner `updated_at`/`version` move on a payout recompute only when the sum actually differs — `services.py:108-115`
- §3.1 — insert — ambiguity — duplicate email/tier, bad month-day ordering, non-past `date_of_birth` all yield `ERR_INVALID_REQUEST` at step 4 — `routes_core.py:38,75,187,227`
- §3.1 — insert — ambiguity — plan cent fields and `full_refund_hours_before` are ≥0; `excluded_causes` required but may be empty — `routes_core.py:180-203`
- §3.2 — insert — ambiguity — `owner_id` resolved (404) then must equal acting owner (`ERR_NOT_RESOURCE_OWNER`) — `routes_listings.py:49-51`
- §3.2 — revise — mismatch — superseded doc's own `version` bumps; listing `version` bumps unconditionally; **verify carries no state precondition** and lands on `VERIFIED` from any status without clearing `superseded` — `routes_listings.py:232,268-272`
- §3.2 — insert — ambiguity — `insurance_status`/`inspection_photo_zone_count` re-evaluated on every read against the clock, not a mutation — `routes_listings.py:18-20,74,90`
- §3.2 — insert — ambiguity — submit-for-review guards run in §2.8 ladder order (photos → docs → owner standing) — `routes_listings.py:102-112`
- §3.3 — insert — ambiguity — cascade credits/touches the renter only on a non-zero refund; assignments voided in `created_at` order; cancelled booking's `delivery_fee_cents`/quote left as-is — `services.py:232-252`
- §3.4 — insert — ambiguity — renter derived fields re-evaluated on read and at booking request without a version bump — `routes_core.py:94`, `routes_bookings.py:147`
- §3.5 — insert — ambiguity — `renter_id` must equal the acting renter, checked after the four-FK round — `routes_bookings.py:83`
- §3.5 — insert — ambiguity — frozen `towing_verified_tier` is the clock-date evaluation, not the end-date one the gates used — `routes_bookings.py:147-158`
- §3.6 — insert — ambiguity — the four creation gates run in ladder order (collision → window → rig/site → delivery-applicable) — `routes_delivery.py:50-63`
- §3.6 — insert — ambiguity — collision test compares only same-campground **and same-`dropoff_date`** windows — `services.py:153-163`
- §3.6 — revise — mismatch — supersession is deferred until all four gates pass (a refused create leaves priors standing), the gating collision test excludes the booking's own priors, the test re-runs after voiding, and a late conflict does not roll the supersession back — `routes_delivery.py:48-69`
- §3.6 — insert — ambiguity — promotion hold true-up has no solvency guard and is the one path that may drive `wallet_credit_cents` negative — `services.py:201-206`
- §3.6 — revise — mismatch — void checks ownership before state, and does **not** increment the booking's `version` despite rewriting its quote — `routes_delivery.py:126-133`
- §3.7 — insert — ambiguity — confirm's recompute reads current listing rates/season rows (only the four frozen values persist) and takes the fee of the earliest `SCHEDULED`/`COMPLETED` assignment; funds check uses the fresh total — `services.py:119-141`
- §3.7 — insert — ambiguity — regression compares only the immediately preceding reading; readings and photos carry no booking-state precondition and don't touch the booking — `routes_bookings.py:339-356,396`
- §3.8 — insert — ambiguity — a claim filed on an already-`DISPUTED` booking leaves the dimension put but still bumps `version` — `routes_claims.py:64-66`
- §3.8 — revise — mismatch — adjudication legal only from `UNDER_REVIEW`; `override_amount_cents` ≥0; an **empty** `override_reason` is `ERR_INVALID_REQUEST` (the 422 covers only an absent one); both inputs stored on the claim — `routes_claims.py:141-159`
- §3.9 — insert — ambiguity — reversal floors `completed_night_count` at 0 and rolls `last_reconciled_at` to the latest remaining settled stamp, or null — `services.py:387-392`
- §3.10 — insert — ambiguity — cancellation records `cancel_reason`, voids in `created_at` order, leaves the booking's `delivery_fee_cents`/quote, and always bumps the renter's `version` even on a zero refund — `services.py:305-313`
- §4 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` (404), bad method → `ERR_METHOD_NOT_ALLOWED` (405), both decided before the header ladder and absent from the §5 catalogue — `app.py:33-42`
- §4 table — insert — ambiguity — `GET /pricing-seasons` is filterable by `season_code` — `routes_core.py:239`

No files under `implementation/` were touched.
