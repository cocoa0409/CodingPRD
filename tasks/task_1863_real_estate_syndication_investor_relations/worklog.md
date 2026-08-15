# Worklog — task_1863_real_estate_syndication_investor_relations

## Step 1: Create Task Directory — 2026-08-14T21:24:00.000Z

Task directory `tasks/task_1863_real_estate_syndication_investor_relations/` and `workspace/` pre-created by pipeline invoker (per /prd-bench-entrance args); orchestrator verified existence and did not create any other task_* directory.

## Step 2: Generate Scaffold — 2026-08-14T21:59:30.000Z

All three files in place.

## Summary

Generated scaffold artifacts for **task 1863 — Real Estate Syndication & Investor Relations** at `/home/ubuntu/github/CodingPRD/tasks/task_1863_real_estate_syndication_investor_relations/`.

**Files:**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` or `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key

**Complexity profile:** Compliance/audit (primary) + Ledger reconciliation (secondary); hierarchical topology; branching state-machine shape; segregation-of-duties role model; layers = optimistic_concurrency, dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation.

**Counts:**
- **Entities:** 15 (Syndication, Investor, Property, Offering, Subscription, SubscriptionDocument, CapitalCall, CapitalCallContribution, QuarterlyReport, Distribution, DistributionLine, CapitalEvent, K1Package, TransferRequest, InvestorPortalSession)
- **State machines:** 11
- **Calculations:** 8 (preferred_return_accrual, distribution_waterfall_allocation, capital_call_prorata_allocation, quarterly_distributable_cash, capital_event_net_distributable, k1_provisional_allocation, k1_final_allocation, transfer_prorata_carryover)
- **Endpoints:** 106 (many are flat filtered-list GETs added to satisfy FK reverse-reachability lint)
- **Errors:** 55
- **Roles:** 4 (SponsorOperator, ComplianceOfficer, TransferAgent, Investor — with Investor entity_backed)
- **Validations:** 30 priorities
- **Concurrency rules:** 2 OCC-guarded endpoints (transfer-create, distribution-approve)
- **Difficulty instances:** 18 (exactly 2 per rule, rules 1–9)
- **Corner instances:** 38 across 8 taxonomy sections (entities, state_machines, calculations, validations, errors, roles, cross_cutting_layers, consistency_model)

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- §1.5 endpoints declared: 106; §1.1 entities declared: 15; §1.8 instances scanned: 18; §1.9 instances scanned: 38; calls scanned: 1069.

**Difficulty-rule differentiation highlights:**
- dual_variant_calc: Subscription pref-accrual (simple vs compounding, +24,322c delta) AND K1Package provisional-vs-final reconciliation (+1c largest-remainder delta)
- combinatorial_formula: mode (c) GP catch-up closed-form resolution of fixpoint equation + mode (b) capital-call per-line rounding + largest-remainder reconciliation
- non_linear_state_machine: Subscription revert cycle + CapitalCall compound/aggregate bubble-up
- transitive_cascade: contribution release → subscription FUNDED → offering totals (depth 3) + distribution pay → capital event DISTRIBUTED (depth 2)
- priority_pair_validation_conflict: state-beats-fiscal on release-escrow + business_safety-beats-constraint on verify-accreditation
- boundary_precision_check: inclusive `>=` on min_subscription_cents vs strict `>` on capital-event gross>debt
- cross_entity_state_dependency: Offering→Property (open requires OWNED) + TransferRequest→Subscription (buyer onboarding)
- resource_temporal_overlap: CapitalEvent lifecycle-occupancy per property vs QuarterlyReport discrete (year, quarter) slot
- compensating_invariant: transfer settle conserves Offering.total_funded_cents; distribution pay conserves sum(line.total_cents) == total_distributable_cents

## Step 3: Copy Shared Files — 2026-08-14T22:01:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1863_real_estate_syndication_investor_relations/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T22:10:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1863_real_estate_syndication_investor_relations/workspace/PRD.md`. The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Summary

**Output**: 357 lines.

**Section list**:
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC & header identity, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 Nested Path Resolution, 2.6 Monetary Precision & Rounding, 2.7 Optimistic Concurrency Control, 2.8 Logical Clock, 2.9 Validation Ordering
- §3 Business Logic: 3.1 Sponsor/Investor/Property setup, 3.2 Offering lifecycle, 3.3 Subscription compliance pipeline, 3.4 Capital calls & escrow, 3.5 Quarterly reports & distribution waterfall, 3.6 Capital events, 3.7 K-1 packages & dual-variant allocation, 3.8 Preferred-return accrual variants, 3.9 Transfers & portal sessions
- §4 Endpoint Definitions (108-row table, 4 columns)
- §5 Error Code Catalogue (54 errors, 2 columns)

**Coverage counts**:
- Entities: 16/16 rendered (14 with common fields, 2 lightweight: `SubscriptionDocument`, `DistributionLine`)
- State machines: 11/11 — all 48 transitions expressed with preconditions, error IDs, and side effects
- Calculations: 8/8 — including the dual-variant preferred-return accrual (0.25 promote threshold), the 4-tier waterfall with GP catch-up algebra, per-line-then-sum vs largest-remainder reconciliation disciplines, and the provisional/final K-1 divergence
- Errors: 54/54 named in prose and catalogued
- Roles: 4/4 with identity semantics (`Investor` entity-backed; other three opaque)

**Hard-contract audit**:
- Contract 1 (field-name coverage): 82 entity fields, 43 request-body keys, 21 query params, 15 path params — all present in backticks, 0 missing. PASS.
- Contract 2 (rule coverage): validation priorities ordered in prose (auth → RBAC → path → state → domain; submit's 4 checks and verify-accreditation's 3 checks explicitly sequenced; overpayment before past-due), both OCC rules fully specified (`expected_subscription_version`/`ERR_STALE_SUBSCRIPTION_VERSION`/412 and `expected_distribution_version`/`ERR_STALE_DISTRIBUTION_VERSION`/412), all cascades stated, sibling branches symmetric. PASS.
- Contract 3 (§3 path purity): 434 backtick tokens scanned in §3, 0 path/method violations. PASS.

**Zero-Silence Rule audit**: no scaffold rules were left unrendered. Three repairs were needed during audit and were applied: (1) `SETTLED` terminal state added to the transfer-settle narrative; (2) explicit `DRAFT → ISSUED`, `ISSUED → CANCELLED`, `CALCULATED → CANCELLED`, and `CLOSED_TO_NEW_SUBSCRIPTIONS → OPEN` state pairs made explicit; (3) full `applies_to` scopes for `ERR_OFFERING_NOT_OPEN` (create/submit/transfer-initiate/publish) and `ERR_SYNDICATION_NOT_ACTIVE` (open/submit/issue) enumerated. One scaffold nuance worth noting: the syndication/offering lifecycle endpoints declare *optional* `expected_syndication_version?`/`expected_offering_version?` inputs — these are not `concurrency_rules` entries, so §2.7 names them as optional fields while stating that only the two scaffold-declared OCC endpoints require a version field.

## Step 5: Generate Unit Tests — 2026-08-14T22:55:00.000Z

Generation complete. Final summary:

## Summary

**Test infrastructure (`test_helpers/`)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1863_real_estate_syndication_investor_relations/test_helpers/`:
- `types.py` — 15 status/kind enums, 15 entity TypedDicts (lighter `id`+`created_at`-only shape for `SubscriptionDocument`/`DistributionLine`/`InvestorPortalSession` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all nested routes, all flat filtered-list reads, `POST /_clock/set_current_utc`)
- `api_errors.py` — all 49 §5 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_timestamp_ms3` (three-fractional-digit rule) + `assert_line_totals_consistent`
- `factories.py`, `constants.py` (reserve 10% / debt 30% / carry-compounding threshold 0.25 / $100K class threshold / 90-day accreditation / 12h sessions)
- `test_users.py` — shared headers for the three opaque roles, two distinct compliance desks (segregation of duties), `make_investor_headers(user_id)` for the entity-backed Investor role
- `fixtures.py` — composite chains: active syndication, open offering, full subscription pipeline (docs→submit→verify→approve with two different officers), capital-call issue/receive/release, funded-offering contexts with clock control, published reports, calculated/approved/paid distributions, executed capital events, K-1 packages, transfer pipeline
- `__init__.py` — barrel export

**Test cases (`test_suite/`)** — `conftest.py` + 10 files, **74 tests**, all collected by pytest cleanly.

**Queue A (Difficulty): 18/18 instances, 39 tests** (every instance ≥2 tests; both boundary instances got X-1/X/X+1 triples).

**Queue B (Corner): 35/38 non-stub instances, 35 tests** (no `excluded_because` stubs exist in the yaml). 3 instances skipped under the PRD-first filter:
1. `entities/offering_enum_invalid_status_filter` — unique-derivability: PRD §2.9 pins `ERR_INVALID_REQUEST` for bad request fields/enums but never says whether an unrecognized *filter* enum yields 400 vs an empty 200 list.
2. `validations/self_transfer_rejected` — unique-derivability: buyer==seller also plausibly fails the "separate subscription" onboarding rule, and PRD pins no guard order on agent-approve, so `ERR_SELF_TRANSFER` vs `ERR_BUYER_NOT_ONBOARDED` is not uniquely determined.
3. `consistency_model/state_change_visible_immediately` — coverage: no verbatim PRD sentence states an immediate read-after-write guarantee (scaffold-only claim).

**Notable adjudications**: `errors/error_offering_not_open_blocks_submit`'s recipe was unreachable as written (PRD §3.3 rejects subscription *creation* on a non-OPEN offering), so the test reaches the same precondition via create-on-OPEN → close-to-new → submit. `entities/syndication_create_returns_draft_with_common_fields` and the version-increment instance assert integer-typed/relative-increment versions, because PRD §2.4 pins "increments by one on every mutation" but never an initial value of 1.

**Stage 2 self-audit: PASS** — 74 tests; every test's docstring ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` tag copied verbatim from the source yamls; zero unknown/duplicate/missing tags; zero untagged tests; every quoted span ≥5 words (91 spans) survives literal substring match against PRD.md; no `skip`/`skipif`/`xfail`; no scaffold references in comments; no DistributionLine-to-subscription field assumptions (lines attributed by uniquely-valued waterfall amounts); files compile and `pytest --collect-only` reports 74/74.

## Step 6: Generate Implementation — 2026-08-14T22:55:00.000Z

Implementation complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1863_real_estate_syndication_investor_relations/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=2.2 |
| `app.py` | 61 | Entry point, blueprint registration, envelope error handlers, before-request lazy-default sweep; binds `0.0.0.0:$PORT` (default 10000) in foreground |
| `db.py` | 32 | In-memory dict store (15 collections) + insertion seq; zero seeding |
| `errors.py` | 93 | Full §1.6 catalog + 5 IDs referenced by scaffold/PRD but missing from the catalog (`ERR_OFFERING_NOT_PUBLISHABLE`, `ERR_SYNDICATION_HAS_OPEN_OFFERINGS` at 409; `ERR_STALE_SYNDICATION_VERSION`, `ERR_STALE_OFFERING_VERSION` at 412; generic `ERR_NOT_FOUND` 404) |
| `response.py` | 46 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; pagination fields in meta |
| `middleware.py` | 49 | `X-User-ID`/`X-User-Role` auth + role gate decorator |
| `validate.py` | 154 | Body shape (400), pagination (limit 1–100 default 10, offset 0), filters, OCC fields |
| `resolve.py` | 123 | Left-to-right nested path resolution with per-entity 404s |
| `serializers.py` | 233 | Wire dicts; light entities (Document/Line/Session) get no `version`/`updated_at` |
| `services/calculations.py` | 175 | All 8 calc modules (below) |
| `services/domain.py` | 169 | Stamping/touch, accrual ledger (lazy read + freeze on leaving FUNDED), offering aggregates, lazy DEFAULTED sweep, future-period guard |
| `routes/` (15 files) | 2087 | One module per resource group + flat reads + clock |

## Endpoint coverage: 106/106 PRD §4 endpoints (107 registered routes; the extra is Flask's built-in `/static`).

## Calculation modules implemented
`preferred_return_accrual` (simple + compounding_quarterly variants, full-quarter rule from PRD §3.8), `distribution_waterfall_allocation` (4 tiers, per-line round-half-up, no reconciliation), `capital_call_prorata_allocation` (per-line + largest-remainder to largest line), `quarterly_distributable_cash` (10%/30% withholdings, floor 0), `capital_event_net_distributable`, `k1_provisional_allocation` (no reconciliation), `k1_final_allocation` (largest-remainder to largest funded line), `transfer_prorata_carryover` (exact-rational ratio on pre-settlement balance). All integer cents via Decimal/exact-integer round-half-up.

## State machines implemented
Syndication (DRAFT/ACTIVE/SUSPENDED/CLOSED + open-offering cascade + close precondition), Offering (DRAFT→OPEN→CLOSED_TO_NEW→FINAL_CLOSE→DISSOLVED with rate-freeze at open, dissolve zero-unreturned + paid-distribution guards), Subscription (submit 4-check order docs→min→cap, verify segregation + doc + $100k class gate, approve chained to AWAITING_FUNDING, reject/resubmit loop, withdraw ownership), CapitalCall (issue pro-rata synthesis, cancel with escrow guard), CapitalCallContribution (escrow receive with overpayment-before-past-due order, release with funded bubble-up, lazy/eager DEFAULTED + portal suspension), QuarterlyReport (publish/amend/republish + duplicate + future-period + lock guards), Distribution (calculate waterfall, OCC approve, pay cascade incl. CapitalEvent DISTRIBUTED, cancel discards lines), CapitalEvent (execute net lock + SALE→SOLD), K1Package (draft/final dual-variant), TransferRequest (sponsor→agent→settle with carryover + zero-drain withdrawal, OCC on create).

## Verification
- `bash start.sh` boots cleanly and binds `0.0.0.0:$PORT` in the foreground via `exec`
- Restart wipes all state (1 syndication before kill → 0 after relaunch)
- 70-check lifecycle smoke suite + 45-check edge suite both fully pass on fresh boots, covering waterfall math to the cent (independently recomputed), compounding accrual, OCC 412s, segregation-of-duties 403s, lazy defaulting, and 404 nesting rules

## Step 7: Run Tests and Iterate — 2026-08-14T23:25:00.000Z

All 8 rounds of the final sweep pass 74/74. Task complete.

## Summary

**Iterations run:** 3 eight-round parallel sweeps (sweep 1: 16 deterministic failures; sweep 2: 4 flaky connection-level failures with rounds 1/2/4 fully clean; sweep 3: **all 8 rounds 74/74 — exit condition met**).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability deletions were needed.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1863_real_estate_syndication_investor_relations/test_helpers/api_client.py` — `ApiClient.__init__` now sets `Connection: close` on the shared `requests.Session`. Root cause of sweep-2 flakiness: the runner SIGKILLs and respawns the server on the same port before every test, and the pooled keep-alive connection from the dead server intermittently raced the RST, failing random tests with `ConnectionResetError`/`RemoteDisconnected`/`IncompleteRead`. Fresh connection per request eliminates the stale pool.

**Fixes applied to `test_suite/`:**
- `test_06_quarterly_reports_and_k1.py` — two `validate_success(api.create_quarterly_report(...))` calls now assert `201` (PRD §4: "Endpoints that create a new resource respond with HTTP 201"); they previously asserted the 200 default.
- `test_07_distribution_waterfall_and_accrual.py` — six `validate_success(_create_distribution(...))` sites now assert `201` (same PRD §4 rule).
- `test_07` `_run_waterfall` — re-dated to fund mid-quarter (2026-02-15, inside Q1) and calculate at 2026-07-01, so "one full quarter elapsed" is uniquely derivable. PRD §3.8's main clause ("full calendar quarters elapsed between `funded_at` and the as-of date") and its qualifier ("only when the as-of date has reached or passed the end of the calendar quarter that follows the quarter containing `funded_at`") diverge for boundary-aligned funding (Q=4 vs Q=3 at 2027-01-01); mid-quarter funding makes all faithful readings agree on Q=1. Tier expectations unchanged (verified identical arithmetic).
- `test_07` `TestPreferredReturnAccrualVariants` — same re-dating (fund 2026-02-15, read 2027-01-01 → unambiguous Q=3): simple 800,000→600,000, compounding 824,322→612,080, divergence 24,322→12,080; `test_variants_diverge_over_four_quarters` renamed to `..._three_quarters`; docstrings updated with the new arithmetic. The dual-variant difficulty coverage is fully preserved.
- `test_08_capital_events.py` — `get_property(prop["id"], SPONSOR)` → `get_property(prop["id"])`; the fixtures helper takes only `property_id` (was a TypeError).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1863_real_estate_syndication_investor_relations/workspace/implementation/routes/contributions.py` — `receive_escrow` state guard now admits `DEFAULTED`. PRD §3.4 names `ERR_ESCROW_PAST_DUE` for "a receipt arriving after the call's `due_date`", and §2.9's own example ("an investor who wires too much money after the due date hears about the overpayment first") presupposes late wires reach the domain guards. Since the PRD's lazy/eager default sweep flips any under-funded past-due contribution to `DEFAULTED` before the handler runs, excluding `DEFAULTED` made `ERR_ESCROW_PAST_DUE` unreachable dead code. A `DEFAULTED` contribution still can never receive funds (default implies past due, so the timeliness guard always fires); `RELEASED` remains rejected by the state guard.

## Step 8: Finalize PRD — 2026-08-14T23:32:00.000Z

Both edits verified against the implementation. Final state: 357 lines in both files (0.0% delta — edits are within-paragraph), diff confined to exactly two paragraphs.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 357 → 357 lines, 0.0% line-count delta; 2 paragraphs changed (lines 132 and 172).

**Changes:**

- **§3.4 — insert** — Pins the escrow-receipt state guard: a receipt is entertained only while the contribution is `PENDING`, `ESCROW_RECEIVED`, or `DEFAULTED`; any other status (a `RELEASED` contribution) is rejected with `ERR_INVALID_STATE`. Also records the two `DEFAULTED` origins' consequences: lateness-defaulted contributions are past `due_date` so their wires reach the overpayment/past-due guards (keeping `ERR_ESCROW_PAST_DUE` and §2.9's overpayment-first example reachable), while cancellation-defaulted contributions may still have `due_date` ahead and an accepted wire is recorded with the contribution remaining `DEFAULTED` — `implementation/routes/contributions.py:44-83` (admitted set at line 57, guards at 61-70, PENDING-only transition at 73-74).
- **§3.8 — revise** — Replaced the ambiguous "A quarter counts as full only when…" qualifier with an explicit counting rule: the count begins with the calendar quarter immediately following the one containing `funded_at` (the funding quarter never counts, even for a first-instant funding), and each quarter counts once the as-of date reaches or passes its final calendar day, with a worked Q1 example — `implementation/util.py:112-131` (`full_quarters_elapsed`), consumed by `implementation/services/calculations.py:26`.

**Step 7 items with no PRD edit (verified already-correct or test-side):** `Connection: close` in `test_helpers/api_client.py` (transport harness concern); the eight 201-assertion fixes in `test_06`/`test_07` (PRD §4 already stated the rule; confirmed impl returns 201 at all 13 create sites); `test_08` `get_property` helper-signature fix (fixture bug).

**Pre-edit search log (NO-NEW-MISMATCH):**

- **Edit 1** — (a) Subject: admitted states and outcomes for an escrow receipt. (b) Enumerated paths: `routes/contributions.py:44-83` (receive), `:89-119` (release, requires `ESCROW_RECEIVED`), `services/domain.py:130-152` (lazy sweep: `PENDING`/`ESCROW_RECEIVED` → `DEFAULTED` only when past-due, under-funded, call `ISSUED`/`PARTIALLY_FUNDED`), `routes/capital_calls.py:104-123` (cancel → `DEFAULTED`, `due_date` possibly still future), `routes/capital_calls.py:80-103` (issue synthesizes `PENDING`), `app.py:31-33` (before-request sweep), `routes/clock.py:20-21` (eager sweep; no monotonicity guard), `resolve.py:62-66` (404 path), grep-confirmed exactly four contribution statuses exist. (c) Wording adjustments: dropped the step_7_diff's own claim "a DEFAULTED contribution can never receive funds" — false for cancellation-defaulted contributions with unpassed due dates (impl records such wires, status stays `DEFAULTED`); also avoided "the timeliness guard always fires" since `clock.py` permits backward moves — final text says lateness-defaulted wires "reach the overpayment and past-due guards" without a universal quantifier.

- **Edit 2** — (a) Subject: full-quarter counting for preferred-return accrual. (b) Enumerated paths: `util.py:112-131` (counting function; date-granularity `as_of.date() >= quarter_end_date`), `services/calculations.py:15-37` (q≤0 → 0; both formulas), `services/domain.py:56-85` (lazy read at `CLOCK.now()`, freeze on leaving `FUNDED`), `serializers.py:84` (every subscription read), `routes/distributions.py:110-113` (eager at calculate, as-of == `calculated_at`), `routes/transfer_requests.py:185` (settle-time read), plus test expectations (funded 2026-02-15 → Q=1 at 2026-07-01, Q=3 at 2027-01-01; simple 600,000 / compounding 612,080 / divergence 12,080 — all reproduce under the pinned rule). (c) Wording adjustments: added "even when funding lands on its first instant" to kill the divergent boundary reading (impl yields Q=3, not Q=4, at 2027-01-01 for Q1-start funding); used "reached or passed that quarter's final calendar day" to preserve impl's date-granularity comparison.

## Step 9: Complete PRD — 2026-08-14T23:40:00.000Z

## Summary

**Source vs output**: `/home/ubuntu/github/CodingPRD/tasks/task_1863_real_estate_syndication_investor_relations/workspace/PRD_FINALIZED.md` (357 lines, 63277 chars) → `PRD_COMPLETED.md` (362 lines, 67122 chars). Char delta: **+3845**.

**Counts**: 9 ambiguity-pins, 5 mismatch-revisions (14 edits total).

### Changes (one bullet each)

- **§2.4 Resource Identity** — revise — mismatch — `InvestorPortalSession` added to the lighter-resource list (no `updated_at`/`version`); also pinned that `version` starts at 1 and `updated_at` refreshes on each mutation — `implementation/services/domain.py:25-37` (`stamp_new_light` used for portal sessions in `routes/investors.py:100`).
- **§2.5 Nested Path Resolution** — insert — ambiguity — pinned that investor-role cross-read of subscription/document/transfer-request returns 404 (`ERR_*_NOT_FOUND`), not 403; portal sessions remain the 403 exception — `implementation/routes/subscriptions.py:24-27`, `routes/documents.py:21-24`, `routes/transfer_requests.py:22-24`, `routes/investors.py:86-88,108-111`.
- **§2.7 Optimistic Concurrency** — revise — ambiguity — named the actual error IDs (`ERR_STALE_SYNDICATION_VERSION`, `ERR_STALE_OFFERING_VERSION`, HTTP 412) returned by the optional-OCC fields on syndication/offering lifecycle actions — `implementation/errors.py:83-85`, `routes/syndications.py:49-51`, `routes/offerings.py:61-63`.
- **§3.1 Syndication close** — revise — mismatch — pinned that close requires `ACTIVE` status and that `FUNDED` subscriptions are treated as terminal for the cascade (only non-`FUNDED`/non-`WITHDRAWN` are withdrawn) — `implementation/routes/syndications.py:93-108`.
- **§3.1 Investor registry / Property lifecycle** — revise — mismatch — pinned duplicate-email rejection as `ERR_INVALID_REQUEST`; pinned that suspend/revoke-portal carry no state guard; replaced the false `OWNED → UNDER_CONTRACT_TO_SELL → SOLD` progression with `OWNED → SOLD` on SALE execute and flagged `UNDER_CONTRACT_TO_SELL` as admitted-but-never-set — `implementation/routes/investors.py:28-29,64-79`, `routes/capital_events.py:80,91-93`.
- **§3.3 Create subscription** — insert — ambiguity — pinned the `ERR_INSUFFICIENT_PERMISSIONS` ownership check when body's `investor_id` doesn't match caller's `X-User-ID` — `implementation/routes/subscriptions.py:42-44`.
- **§3.3 Resubmit / Withdraw** — revise — mismatch — pinned that resubmit is role-only (no per-subscription ownership check: any `Investor` caller may resubmit any `SUITABILITY_REJECTED` subscription); pinned withdraw's ownership rejection as `ERR_INSUFFICIENT_PERMISSIONS` — `implementation/routes/subscriptions.py:207-217,223-233`.
- **§3.5 Waterfall tier 3** — insert — ambiguity — pinned the degenerate case: when `carried_interest_pct >= 1.0` the catch-up target is the entire remainder after tiers 1+2 (avoids division by non-positive `one_minus`) — `implementation/services/calculations.py:75-79`.
- **§3.5 Distribution create lineage** — insert — ambiguity — pinned that `QUARTERLY_OPERATING` requires the linked report to belong to the same offering (`ERR_QUARTERLY_REPORT_NOT_FOUND` otherwise), `CAPITAL_EVENT` only requires the event to exist (`ERR_CAPITAL_EVENT_NOT_FOUND`) with no property/syndication cross-check, and a body with both or neither reference is `ERR_INVALID_REQUEST` — `implementation/routes/distributions.py:35-48`.
- **§3.7 K-1 base definition** — revise — ambiguity — pinned that the base is "currently `FUNDED` and `funded_at` on or before the tax year's last day", re-evaluated independently at submit and at finalize (so interim subscription/report changes shift the final map's input set) — `implementation/routes/k1_packages.py:26-35,95-104,118-124`.
- **§3.9 Transfer create guard order** — revise — mismatch — pinned the actual guard order at create: investor exists → ownership → OCC version → offering OPEN (PRD previously read as OPEN before OCC) — `implementation/routes/transfer_requests.py:36-46`.
- **§3.9 Transfer settle buyer check** — insert — ambiguity — pinned that settle re-checks the buyer holds a `FUNDED` subscription (rejecting with `ERR_BUYER_NOT_ONBOARDED` otherwise) and that the earliest-created `FUNDED` buyer subscription receives the balance when several exist — `implementation/routes/transfer_requests.py:172-182`.
- **§3.9 Portal sessions** — revise — mismatch — pinned that `last_accessed_at` is stamped only at mint (not updated on reads); that mint is self-only (`ERR_INSUFFICIENT_PERMISSIONS` on cross-investor); that cross-investor session list is `ERR_INSUFFICIENT_PERMISSIONS` — `implementation/routes/investors.py:82-116`.
- **§5 Error table** — insert — mismatch — added five missing catalog entries: `ERR_STALE_SYNDICATION_VERSION` (412), `ERR_STALE_OFFERING_VERSION` (412), `ERR_OFFERING_NOT_PUBLISHABLE` (409), `ERR_SYNDICATION_HAS_OPEN_OFFERINGS` (409), `ERR_NOT_FOUND` (404 fallback for distribution lines / portal sessions / unmatched routes) — `implementation/errors.py:78-88`.

Output: `/home/ubuntu/github/CodingPRD/tasks/task_1863_real_estate_syndication_investor_relations/workspace/PRD_COMPLETED.md`.

## Final Verification Sweep (orchestrator) — 2026-08-14T23:55:00.000Z

Re-ran the 8-round parallel sweep after Step 9 (results files had not persisted in workspace/implementation/). All 8 rounds: 74/74 passed. results.{1..8}.json now present in workspace/implementation/.
