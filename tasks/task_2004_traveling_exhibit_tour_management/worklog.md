# Worklog — task_2004_traveling_exhibit_tour_management

## Step 2: Generate Scaffold — 2026-08-15T06:32:00.000Z

All three artifacts generated at `/home/ubuntu/github/CodingPRD/tasks/task_2004_traveling_exhibit_tour_management/` with a clean `scaffold_lint.py` verdict.

## Summary

**Scenario (verbatim, untouched)**: traveling exhibit tour management covering venue booking/route sequencing, participation fees, crate shipping, condition inspection/damage claims, marketing kits/sponsorship rights, insurance certificates, and refurbishment/retirement.

**Complexity profile**: primary archetype `temporal_windowing` + secondary `posture_driven_gating`; layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; hybrid topology; branching state machines; peer-roles RBAC.

**Counts**:
- **Entities: 10** — Tour, Venue, TourStop, ParticipationContract, Crate, Shipment, ConditionReport, DamageClaim, MarketingKit, InsuranceCertificate
- **State machines: 8** — non-linear highlights: Tour cyclic refurbishment loop (ON_TOUR ↔ IN_REFURBISHMENT), TourStop branching revert (TEARDOWN → OPEN REOPEN), Shipment cycle (RECEIVED → DAMAGE_HOLD → RECEIVED), ConditionReport DISPUTED branch
- **Calculations: 6** — participation_fee (tiered + credit cap, PROVISIONAL/FINAL/FINAL_CANCEL variants), condition_score (weighted + seal-breach cap, PACK/UNPACK variants), damage_claim_payout (pinned per-line-then-sum rounding), marketing_kit_cost (strict `> 3` bulk-discount threshold), route_sequence (install_start, created_at tie-break), insurance_coverage_check (end-exclusive window)
- **Endpoints: 53** (includes `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default, plus flat read aliases for FK reverse-reachability)
- **Errors: 19** (18 domain + ERR_INVALID_REQUEST)
- **Validations: 18** priority-ordered (auth → existence → state/OCC → safety → temporal → constraint → referential → fiscal)
- **Roles: 5** (TourManager, VenueRegistrar, Registrar, Shipper, Insurer), 1 OCC concurrency rule (`stop-book-stale-tour`, 412 ERR_STALE_VERSION)
- **Difficulty instances (§1.8): 18** — exactly 2 per each of the 9 rules, with all rule differentiation clauses honored (different entity domains for dual-variant, modes (a) vs (b) for combinatorial, different entities for non-linear machines, different triggers/depths 3 and 3 for cascades, state-vs-temporal and state-vs-fiscal priority pairs, attendance-tier vs language-count boundaries on different endpoints, TourStop↔Certificate and Contract↔TourStop cross-entity pairs, half-open adjacency vs aggregate-gap overlap semantics, crate-count vs money-ledger invariants). All formula-derived assertions are precomputed literals (verified by executing the formulas in Python: 1700000/2200000 fees, 950000 capped credit, 510000 cancel penalty, 84/40/54 condition scores, 30-cent rounding-order payout, 285000/303000 kit boundary).
- **Corner instances (§1.9): 32 total / 28 active** across sections entities, state_machines, calculations, validations, endpoints, errors (4 `excluded_because` stubs citing §1.8 coverage), rbac, cross_cutting_layers (OCC version-bump, derived-field reconciliation, clock default + certificate activation).

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (53 endpoints, 10 entities, 18 §1.8 + 28 §1.9 active instances, 511 calls scanned.)

Note: a `workspace/` subdirectory already existed in the target dir (created externally during the session); I left it untouched. No sibling tasks were read at any point.

## Step 3: Copy Shared Files — 2026-08-15T06:32:30.000Z

Copied ./INSTRUCTION.md to tasks/task_2004_traveling_exhibit_tour_management/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T06:56:00.000Z

PRD generation is complete and all three hard contracts pass verification. Here is the summary.

## Deliverable

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_2004_traveling_exhibit_tour_management/workspace/PRD.md` — **279 lines**

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Section List

- **§1. Introduction** (2 paragraphs — business-context angle)
- **§2. Global Specifications & System-Wide Principles** — 2.1 RBAC, 2.2 API Response Structure (verbatim block, byte-identical match confirmed), 2.3 Pagination, 2.4 Logical Time and the Certificate Clock, 2.5 Common Resource Properties, 2.6 Money/Condition Scores/Rounding Discipline, 2.7 OCC on Route Booking, 2.8 Nested Resource Resolution and Validation Ordering, 2.9 Tour Posture and Cross-Entity Cascades
- **§3. Business Logic & Workflows** (9 subsections) — 3.1 Tours/Venues/Crate inventory, 3.2 Route booking/windows/sequencing, 3.3 Contracts/tiered fees/sponsorship, 3.4 Marketing kits, 3.5 Insurance, 3.6 Shipment legs, 3.7 Condition inspection/damage claims, 3.8 Installation→Open→Teardown→Close, 3.9 Refurbishment/retirement/ledger
- **§4. Endpoint Definitions** — 4-column table, **53 endpoints**
- **§5. Error Code Catalogue** — 2-column table, **19 errors**

## Hard Contract Reports

**Contract 1 (Field-Name Coverage)**: 77 required identifiers (all `entities[].fields[].name`, endpoint `input`/output keys, query params, `line_items` sub-fields `description`/`amount_cents`, common properties) — **77 present, 0 missing. PASS.**

**Contract 2 (Rule Coverage)**: all 42 state transitions across 8 machines expressed with actors, preconditions, error IDs, and side effects; all 6 calculations rendered as precise prose (tiered participation fee with PROVISIONAL/FINAL/FINAL_CANCEL variants and pinned uplift→credit-cap→subtract order; condition score 40/60 weighting with seal-breach cap at 40 and damage threshold 70; claim payout with per-line 80% round-half-up before summing, capped at 90% of claimed; kit cost $1,500 base + $450/language with 15% bulk discount strictly above 3 languages + $200/logo slot; chronological `seq` with `created_at`-only tie-break; 4-clause insurance coverage rule); all 18 validations matched to their error IDs with explicit priority orderings where checks share an endpoint (booking: `ERR_STALE_VERSION` → double-booking → gap → window shape; BEGIN_INSTALL: state → insurance → supervision); the single OCC rule fully expressed (`expected_tour_version`, tour `version`, `ERR_STALE_VERSION`, HTTP 412); sibling symmetry maintained (three RETIRE branches, DENY/PAY hold release, ACCEPT from both SUBMITTED and DISPUTED, kit/certificate void sweeps). **PASS.**

**Contract 3 (§3 Path Purity)**: 450 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS.**

Additional checks: all 41 state/enum values and all 24 transition action names appear as exact backticked strings; all 19 error IDs appear in §2/§3 prose, not just the catalog; no fuzzy/approximating wording; no operator-syntax leakage. One scaffold gap noted: `CLIMATE_EXEMPT_CRATE_MAX` has no value defined anywhere in the scaffold, so the PRD renders the supervision rule faithfully as "the climate-exempt crate ceiling" without inventing a number.

## Step 5: Generate Unit Tests — 2026-08-15T07:15:00.000Z

`file_report` is imported but now unused in test files (it's used inside fixtures). Harmless — it's part of the barrel import pattern. Everything passes:

- All files parse.
- Every test has exactly one `Design:` tag, at docstring end, resolving to a real instance.
- All 121 PRD citations have a distinctive ≥8-word verbatim substring in PRD.md.
- No skip/xfail/scaffold-leakage.

The generation is complete. Summary:

## Summary

Generated test infrastructure and suite for `task_2004_traveling_exhibit_tour_management`.

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2004_traveling_exhibit_tour_management/test_helpers/` (9 files):** `types.py` (9 status enums + role enum + 10 TypedDicts), `api_client.py` (57 endpoint methods covering all PRD §4 routes including flat read aliases), `api_errors.py` (19 error IDs with HTTP status map registered via `set_error_http_status_map`), `assertions.py` (per-entity structural assertions), `factories.py` (input-field-only payload factories with unique label/code generation), `constants.py` (fee tiers, score weights, payout percents, kit cost constants), `test_users.py` (5 opaque-role header sets), `fixtures.py` (5-tier composite setups: open-booking → contracted stop → received shipment → install-ready → teardown → closed stop, plus report/claim lifecycle helpers), `__init__.py` (barrel export).

**Stage 2 — `/home/ubuntu/github/CodingPRD/tasks/task_2004_traveling_exhibit_tour_management/test_suite/` (10 test files + conftest.py, 81 tests):**
- `test_01_tour_and_stop_basics.py` — creation defaults, required fields, 404, window malformed, supervision computation
- `test_02_route_booking.py` — seq assignment, OCC version increment, half-open venue overlap, refurbishment gap, stale-version priority
- `test_03_participation_fees.py` — tier boundaries 10000/10001, credit-cap binding, provisional-vs-final divergence, ledger conservation, SIGN cross-entity flip, sponsorship-cap/duplicate-contract rejections
- `test_04_shipments_and_insurance.py` — route consecutiveness, insurance window end-exclusivity boundary, BEGIN_INSTALL insurance gate, crate location conservation
- `test_05_condition_reports_and_claims.py` — composite score seal variants, damage-hold cascade blocking install, hold release cycle, per-line payout rounding, claim mismatch, off-manifest crate, state-beats-fiscal priority, derived condition_score
- `test_06_stop_lifecycle.py` — TEARDOWN→OPEN reopen branching, CLOSED terminal lockdown (parametrized over 5 actions), attendance gate, supervisor gate
- `test_07_tour_retirement.py` — retire gates, RETIRED terminal, full retirement cascade
- `test_08_marketing_kits.py` — bulk-discount boundary at language_count 3 vs 4
- `test_09_listing_summary_clock.py` — pagination envelope, crate location filter, zero financial summary, certificate clock activation
- `test_10_rbac.py` — role denials for tour creation, contract signing, shipment dispatch

**Coverage audit:** Queue A — all 18 difficulty instances × 2 tests each = 36. Queue B — all 28 non-stub corner instances ≥1 test each = 45. Total 81 `Design:` tags, zero orphans, zero untagged tests.

**Skipped instances:** None. All 18 queue-A and all 28 non-stub queue-B instances passed the PRD-first two-condition filter. The 4 `errors` section stubs (`err_no_insurance_coverage_triggerable`, `err_stale_version_triggerable`, `err_venue_double_booked_triggerable`, `err_refurbishment_gap_violated_triggerable`) are `excluded_because:` stubs owned by difficulty instances — not translated, per the skill spec.

**Verification:** all files parse; every docstring ends with exactly one valid `Design:` line; all 121 quoted PRD citations have a distinctive ≥8-word verbatim substring in PRD.md; no scaffold references, no skip/xfail markers; `test_helpers` package imports cleanly.

## Step 6: Generate Implementation — 2026-08-15T07:32:00.000Z

Implementation complete. All files live under `/home/ubuntu/github/CodingPRD/tasks/task_2004_traveling_exhibit_tour_management/workspace/implementation/`.

## File list

- `start.sh` — executable launcher; guarded `pip install` (no-op once Flask is importable), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, blueprint registration, `before_request` auth, envelope-shaped error handlers (ApiError / 404 / 405 / generic)
- `db.py` — empty-at-boot in-memory stores (no seeding), logical clock (fixed default `2026-08-01T00:00:00Z`, never wall-clock), UUID minting, strictly monotonic 3-fractional-digit UTC timestamps (makes the `created_at` route-seq tie-break always decidable), `touch()` version bumping
- `errors.py` — ApiError + the full 19-error catalog with catalogued HTTP statuses
- `envelope.py` — `meta`/`response_type`/`data` envelope; pagination fields (`limit`/`offset`/`total_count`/`has_more`) in `meta` for lists; `req_`-prefixed request ids
- `security.py` — `X-User-ID`/`X-User-Role` auth (401) and role gates (403) for the five roles
- `validate.py` — payload/type/datetime validation (400), left-to-right parent-scoped path resolution (404), pagination with defaults 10/1/100/0 (clamped), filter application, `created_at`-ascending sort
- `calc.py` — all six calculations with `Decimal` round-half-up at exactly the pinned steps: tiered participation fee (10k/50k tiers, 10%/25%, three-way credit cap), FINAL_CANCEL 30%-of-provisional penalty, weighted condition composite (0.4/0.6, seal-breach cap 40, damage threshold 70), per-line-then-sum-then-cap claim payout (80%/90%), marketing kit cost (base 150000, 45000/lang with >3-lang 15% discount, 20000/logo), route resequencing by `(install_start, created_at)`, four-clause end-exclusive insurance coverage
- `system.py` — cascades: clock-set cert sweep (ISSUED→ACTIVE→EXPIRED), contract finalization + ledger recompute, stop-cancel cascade, close-stop finalization + refurbishment trigger (strictly-greater gap), retirement cascade, damage-hold release
- `serializers.py` — explicit per-entity field whitelists; window datetimes echo the exact input strings
- `routes/` — `tours.py` (clock, tours, venues, financial-summary), `crates.py`, `stops.py` (booking + PATCH + 6 transitions + assign-supervisor), `contracts.py`, `kits.py`, `certs.py`, `shipments.py`, `reports.py`, `claims.py`, `flat.py` (16 flat read aliases)

## Endpoint count

**53 endpoints** — the full scaffold Table 5: 37 primary (clock, tour/venue/crate/stop/contract/kit/cert/shipment/report/claim groups, financial-summary) + 16 flat read aliases.

## Verification

128 smoke checks replaying every `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` recipe pass on fresh boots: fee variant divergence (1700000→2200000), seal-breach 40 vs intact 84, tier boundary 10000/10001, kit 3-vs-4 boundary (285000/303000), payout rounding order (30 not 31), DAMAGE_HOLD cycles, teardown/reopen branching, retirement cascade, stale-version-beats-double-booking, state-beats-fiscal on APPROVE, half-open venue adjacency, exact-5-day gap acceptance, out-of-order route resequencing (seq 1/2/3), OCC +1, clock activation/expiry, RBAC denials, and the full two-stop refurbishment interlude (IN_REFURBISHMENT → second leg → back ON_TOUR; retire-from-refurbishment returns crates to AT_ORIGIN).

## Interpretation decisions (PRD admitted multiple readings)

1. **`CLIMATE_EXEMPT_CRATE_MAX` is undefined** — the worklog flags this as a known scaffold gap; the PRD deliberately says only "the climate-exempt crate ceiling". I set it to 10, which satisfies every documented scenario (all climate-controlled recipes use ≤3 crates and expect no supervisor).
2. **BEGIN_INSTALL with no inbound shipment at all**: the design recipe (no shipment, no cert) expects `ERR_NO_INSURANCE_COVERAGE`, while PRD §3.8 lists the shipment-state precondition as biting "first". I kept PRD's check order but treat the shipment precondition as applicable only when an inbound shipment exists (vacuous when absent), so both the no-shipment/no-cert case (→ `ERR_NO_INSURANCE_COVERAGE`) and the DAMAGE_HOLD case (→ `ERR_INVALID_STATE`) behave as specified.
3. **Retirement finalization of never-sent contracts**: PRD §3.9 deems `final_fee_cents = provisional_fee_cents`, but the design test expects 0 for a DRAFT contract (null provisional). I finalize with the provisional when present, else 0.
4. **Design-doc self-conflict on booking-check order**: the refurb-gap recipe's trigger stop also overlaps an existing stop at the same venue (would be `ERR_VENUE_DOUBLE_BOOKED`), while the half-open-overlap recipe simultaneously violates the gap rule and expects `ERR_VENUE_DOUBLE_BOOKED`. The two recipes demand opposite orders; I followed the PRD §3.2 / scaffold-priority order (stale-version → double-booked → gap → window-shape), since PRD is the declared winner.
5. **PACK-report gating when `origin_stop_id` is null** (first leg): the recipes file PACK reports against the inbound leg while the stop is in TEARDOWN, so the "origin stop in {TEARDOWN, CLOSED}" gate resolves to the shipment's destination stop when origin is null.
6. **Uncatalogued rejections** map to `ERR_INVALID_REQUEST` (400): duplicate `exhibit_code`, duplicate `crate_label` within a tour, certificate `coverage_cents < declared_value_cents`, body-referenced ids that don't exist (venue, destination stop is 409 per priority 13, report-on-claim). `expected_tour_version` missing/wrong-typed → 400; numeric strings coerced.
7. **Route `seq` is reassigned globally on each booking** (the out-of-order booking recipe requires earlier-booked stops to be renumbered), and each resequenced stop gets its own version bump per PRD §2.5.
8. **Pagination**: out-of-range `limit` clamps to [1,100] (rather than 400); non-integer `limit`/`offset` → 400. Contract and marketing-kit "get" endpoints return paginated arrays (tests index `$.data[0]`).
9. `supervisor_user_id` is stored on the stop for the install gate but kept out of the stop's serialized fields (the entity model doesn't declare it); it appears only in the assign-supervisor response, which the endpoint table pins to `{supervisor_user_id, tour_stop_id}`.

## Step 7: Run Tests and Iterate — 2026-08-15T07:56:00.000Z

All 8 rounds pass 89/89 with zero failures. Clean sweep — exiting.

**Summary**

- **Iterations run:** 2 (iteration 1: 2 deterministic failures in all 8 rounds; iteration 2: clean 89/89 across all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`** (file: `/home/ubuntu/github/CodingPRD/tasks/task_2004_traveling_exhibit_tour_management/test_suite/test_02_route_booking.py`, class `TestRouteSequence`):
  - `test_seq_assigned_by_install_start_not_creation_order` and `test_seq_visible_on_list_read` — two test bugs fixed, both violations of PRD fidelity rather than implementation bugs:
    1. Both tests passed the venue **dict** (`vc`, `va`, `vb`) as `venue_id` to `create_stop_payload`; PRD §3.2 requires the payload to name the `venue_id` (a string id), so the server's `ERR_INVALID_REQUEST` was correct. Changed to `vc["id"]` / `va["id"]` / `vb["id"]`.
    2. Both tests asserted final `seq` values on **create-response snapshots** (e.g., `s_dec["seq"] == 3` on the first stop booked onto an empty tour). PRD §3.2 pins the new stop's seq at booking time as "one plus the number of existing stops ... that sort strictly earlier" (= 1 there), so no PRD-faithful server could ever satisfy those snapshot assertions. The final chronological ranking is observable only by re-reading after all bookings (out-of-order insertion renumbers the route, keeping the total order §3.6's "consecutive stops by route `seq`" requires). Both tests now re-read via `list_stops` and assert the final ranking (Sep=1, Oct=2, Dec=3); this also matches `test_seq_visible_on_list_read`'s stated intent, which never actually performed a list read.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:** none — the implementation (global seq reassignment in `calc.assign_route_seqs`, invoked per booking in `routes/stops.py`) was already PRD-faithful.

## Step 8: Finalize PRD — 2026-08-15T08:05:00.000Z

Done. The task is complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_2004_traveling_exhibit_tour_management/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 279 lines → PRD_FINALIZED.md 279 lines (one paragraph extended in place); 42,603 → 43,023 chars, **+0.99%**.

### Changes (1 edit)

- **§3.2 — insert** — Appended two sentences to the seq-assignment paragraph pinning that booking re-stamps the whole route: the same `(install_start, created_at)` chronological ordering is applied to every stop of the tour of any status, each stop's `seq` is set to its 1-based rank in that order, an out-of-order booking renumbers existing stops (so a previously read `seq` may change after a later booking), and each stop whose `seq` changes counts as mutated under §2.5 — `implementation/calc.py:113-123` (`assign_route_seqs`), invoked per booking at `implementation/routes/stops.py:109`.

### Step_7_diff items requiring no edit

- **`venue_id` passed as dict rejected with `ERR_INVALID_REQUEST`** — pure test fixture bug; PRD already determines string-id typing via §2.5 (`id` (string)) + §3.2 ("a payload naming the `venue_id`"), matching `routes/stops.py:35`.
- **Create-response snapshot showing at-booking seq** — already determined by the §3.2 formula ("one plus the number of existing stops … that sort strictly earlier") plus §2.2 (creates return the created resource); only the *renumbering of existing stops* was silent, which is the edit above.

### Per-edit pre-edit search log (NO-NEW-MISMATCH)

- **(a) Subject:** `seq` assignment / re-stamping on stop booking.
- **(b) Impl paths enumerated and read/grepped:** `calc.py:113-123` (`assign_route_seqs` — global, all statuses, touch-only-on-change); `routes/stops.py:93-111` (book_stop creates with `seq=None`, then re-derives); `routes/stops.py:114-159, 202-324` (list/get/PATCH/transitions never alter seq); `serializers.py:15` (seq in every stop representation); `routes/shipments.py:47-58` (consecutiveness reads `dest.seq == 1` / `origin.seq + 1 == dest.seq`, relying on contiguous ranks that include cancelled stops); `system.py:141-156, 161-165, 168-199, 204-229` (`cancel_stop`, `close_stop_effects`, `maybe_enter_refurbishment`, `retire_tour` — none re-derive seqs); `validate.py:182` (`sorted_created` — lists order by `created_at`, not seq).
- **(c) Wording adjustments made:** scoped re-stamping to booking only (cancel/close/retire never renumber); repeated "of any status whatsoever, live or cancelled" so cancelled stops keep ranks (required by the shipments consecutiveness check); limited mutation bookkeeping to "each stop whose `seq` changes" (impl touches only on actual change); made no claim about list sort order, leaving §2.3's `created_at` default intact.

## Step 9: Complete PRD — 2026-08-15T08:18:00.000Z

All 31 edits landed across 27 changed lines (four lines each received two edits: §3.5's first paragraph, §3.7's claim paragraph, §3.8's OPEN/REOPEN paragraph, §3.9's cascade paragraph). Line count unchanged at 279 — every change is an in-paragraph insert or in-place revision, no new sections.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (279 lines / 43,264 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_2004_traveling_exhibit_tour_management/workspace/PRD_COMPLETED.md` (279 lines / 47,590 chars). Char delta: **+4,326**.

**Counts**: 28 ambiguity-pins, 3 mismatch-revisions (31 edit operations total).

**Changes** (one per bullet):

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400); out-of-range values clamped (`limit`→[1,100], `offset`→≥0), not rejected — validate.py:143-169
- §2.4 — insert — ambiguity — both cert sweeps (ISSUED→ACTIVE, ACTIVE→EXPIRED) run on every clock advancement, so a fully-past window lands directly in `EXPIRED` — system.py:113-122
- §2.5 — insert — ambiguity — client-supplied timestamps (windows, coverage, leg schedules) are stored and echoed verbatim, unnormalized — validate.py:53-59, serializers.py:1-3
- §2.6 — insert — ambiguity — integer quantities carry no minimum unless §3 states a floor; zero/negative accepted — validate.py:37-43, tours.py:38-40
- §2.7 — insert — ambiguity — `expected_tour_version` must be an integer; numeric strings coerced — validate.py:73-80
- §2.8 — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404) — app.py:34-42
- §3.1 — insert — ambiguity — duplicate `exhibit_code` → `ERR_INVALID_REQUEST` (400) — routes/tours.py:41-43
- §3.1 — insert — ambiguity — duplicate `crate_label` within tour → `ERR_INVALID_REQUEST` (400) — routes/crates.py:22-25
- §3.2 — insert — ambiguity — booking not gated on tour `status`; unknown `venue_id` → `ERR_INVALID_REQUEST` (400); climate-exempt crate ceiling pinned at **ten crates** — stops.py:29-50, calc.py:38
- §3.2 — insert — ambiguity — refurbishment gap measured against immediate chronological neighbours of any status (live or cancelled), both directions — stops.py:65-85
- §3.2 — insert — ambiguity — revising `projected_attendance` after `TENTATIVE` → `ERR_INVALID_STATE` (409) — stops.py:142-145
- §3.2 — insert — ambiguity — supervisor assignment accepted in any stop status; `supervisor_user_id` returned only by the assignment call, absent from stop reads — stops.py:164-177, serializers.py:15-17
- §3.3 — insert — ambiguity — contract transition with no non-terminal contract → `ERR_INVALID_STATE` (409) — contracts.py:69-71
- §3.4 — insert — ambiguity — multiple kits per stop allowed; press-release/transition act on latest non-`RETIRED` kit; none → `ERR_NOT_FOUND` (404), all retired → `ERR_INVALID_STATE` (409) — kits.py:46-54
- §3.4 — revise — **mismatch** — kit sweep to `RETIRED` scoped to `CONTRACTED`-stop cancellation or tour retirement; `TENTATIVE` cancel leaves kits untouched — system.py:141-154
- §3.5 — insert — ambiguity — certificate creation constraints (stop of same tour, coverage ≥ declared value, `effective_from` < `effective_to`) all → `ERR_INVALID_REQUEST` (400) — certs.py:21-38
- §3.5 — revise — **mismatch** — certificate voiding scoped to `CONTRACTED`-stop cancellation or retirement; `TENTATIVE` cancel leaves certificates untouched — system.py:144-154
- §3.6 — insert — ambiguity — every `crate_ids` entry must name a crate of the same tour, else `ERR_INVALID_REQUEST` (400) — shipments.py:34-42
- §3.7 — insert — ambiguity — `PACK` submission on the null-origin first leg is gated on the destination stop — reports.py:103-113
- §3.7 — insert — ambiguity — `condition_report_id` must reference a report on the same shipment, else `ERR_INVALID_REQUEST` (400) — claims.py:39-42
- §3.7 — revise — ambiguity — nested per-shipment claims list carries only the `status` filter; `shipment_id`/`condition_report_id` belong to the flat collection — claims.py:62-70, flat.py:99-103
- §3.8 — insert — ambiguity — BEGIN_INSTALL inbound-leg semantics: any `DAMAGE_HOLD` leg blocks; else latest-created `RECEIVED`/`CLEARED` is the leg; no bound shipment → precondition vacuous and insurance window clauses skipped — stops.py:182-199, 235-241, calc.py:94-110
- §3.8 — insert — ambiguity — OPEN_TO_PUBLIC applies the same inbound-shipment gate (`DAMAGE_HOLD` → `ERR_INVALID_STATE`); vacuous when no shipment bound — stops.py:265-277
- §3.8 — insert — ambiguity — REOPEN against a finalized contract fails with `ERR_INVALID_STATE` (409) — stops.py:290-299
- §3.8 — revise — **mismatch** — CLOSE_STOP crate check: every crate still `AT_VENUE` on the stop needs an `ACCEPTED` `PACK` report filed against **any shipment of the tour whose manifest carried it** (not specifically the outbound); missing → `ERR_INVALID_STATE` (409) — stops.py:307-317
- §3.8 — insert — ambiguity — `TENTATIVE` cancel leaves kits/certificates untouched (explicit); `CONTRACTED` cancel blocked by an in-flight inbound shipment → `ERR_INVALID_STATE` (409) — stops.py:213-226, system.py:141-156
- §3.9 — revise — ambiguity — refurbishment entry requires the **next stop in route order** to be `TENTATIVE`/`CONTRACTED` — system.py:179-189
- §3.9 — insert — ambiguity — a never-sent contract (provisional null) finalizes at zero on retirement — system.py:212-215
- §3.9 — insert — ambiguity — retirement from `IN_REFURBISHMENT` also empties crates' `current_stop_id` — system.py:222-227
- §3.9 — insert — ambiguity — `outstanding_cents` = `total_billed_cents` − `total_collected_cents` — tours.py:144-148
- §4 — revise — ambiguity — flat contracts list is also filterable by `status` — flat.py:49-52

**Notable finding**: the only true PRD-vs-impl contradictions were the cancel-cascade scopes — PRD §3.4/§3.5 described kit retirement and certificate voiding on *any* stop cancellation, while `system.cancel_stop` performs those sweeps only for `CONTRACTED` stops (TENTATIVE cancels only finalize the contract at zero). The CLOSE_STOP PACK-report scope was the third mismatch. Everything else was PRD silence pinned to impl behavior.
