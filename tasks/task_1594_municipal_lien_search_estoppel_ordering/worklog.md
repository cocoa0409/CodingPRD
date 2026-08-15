# Worklog — task_1594_municipal_lien_search_estoppel_ordering

## Step 1: Create Task Directory — 2026-08-14T00:05:00.000Z

Task directory `tasks/task_1594_municipal_lien_search_estoppel_ordering/` and `workspace/` pre-created and pre-assigned by the invoking pipeline (Step 1 treated as DONE per command args).

## Step 2: Generate Scaffold — 2026-08-14T01:02:12.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/`)

- **SCAFFOLD.yaml** — §1.0–§1.7: verbatim response envelope; 9 entities (Jurisdiction, JurisdictionStatute, Department, Association, SearchOrder, ResearchTask, EstoppelOrder, Discrepancy, Delivery); 5 state machines; 2 OCC concurrency rules (`order-patch-stale-version`, `task-findings-stale-version`); 9 calculations; 10 prioritized validation tiers; 48 endpoints (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default); 28 error codes; 5 RBAC roles (all `identity: opaque`).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule groups × 2 instances = 18, each with structured `setup_api_calls`/`trigger` chains and pre-computed literal asserts.
- **SCAFFOLD_CORNER_DESIGN.yaml** — 66 corner instances (51 active + 15 `excluded_because` stubs) across all nine claim-extraction-guide sections; every error code is exercised by at least one instance or stub.

## Key design choices

- **Archetype**: compliance/audit primary + workflow orchestration secondary; flat topology (all peer resources, FK-linked, reverse-reachable GETs); cyclic state-machine shape; segregation-of-duties role model (payoff verifier ≠ researcher; discrepancy resolver ≠ filer).
- **Difficulty highlights**: dual-variant estoppel fee (on-time vs statutory late forfeiture) and provisional-vs-confirmed missed-item liability capped at the delivered snapshot; mode-(b) per-finding rounding on code-violation accrual vs mode-(c) pinned 5-step circular evaluation of the extended-coverage liability cap (provisional cap → coverage fee → final cap); 4-link clock-sweep cascade (estoppel EXPIRED → payoff recompute → order revert → delivery VOIDED); half-open statute windows (adjacency allowed) vs closed parcel service windows (adjacency rejected) vs aggregate rush daily capacity; OCC on order PATCH and findings overwrite; statute version-pinning at jurisdiction identification.

## Verification

`scaffold_lint.py` verdict (final run, pasted verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (48 endpoints, 9 entities, 18 §1.8 + 53 §1.9 active instances, 721 calls scanned). Additional passes: no forbidden concurrency vocabulary, all 86 instance names unique across both design files, all 28 errors referenced by validations/transitions/concurrency rules, all grounds resolve, all stub references point at real §1.8 instances, and all formula-derived asserts were pre-computed with Python (e.g., accrual 19135, coverage fee 2500 with final cap 35000 escaping the 25000 floor, capped liability 100000).

One auth-model note: the missing-header negative test relies on the lint's negative-name exemption (no `as:` field), which the unit-test generator should transcribe as "send without X-User-Role".

## Step 3: Copy Shared Files — 2026-08-14T01:02:50.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1594_municipal_lien_search_estoppel_ordering/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T01:13:27.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/workspace/PRD.md` (the forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened).

**Structure.** A 2-paragraph introduction; §2 with nine domain-derived subsections (RBAC, verbatim §2.2 response structure, pagination, the logical clock and time-driven sweeps, common resource properties, monetary precision/rounding discipline, OCC, the ordered 10-stage validation pipeline, and half-open statute windows); §3 with eight lifecycle-grouped subsections (reference book → order intake/rush admission → jurisdiction identification → research execution → estoppel lifecycle → verification/delivery/liability snapshot → mid-flight corrections → discrepancy claims); §4 with a 48-row, 4-column endpoint table; §5 with a 28-row, 2-column error catalogue.

**Key rules rendered in prose:** the pinned 5-step liability-cap algorithm (base → provisional clamp of 10× between 25000/100000 → 10% coverage fee rounded half-up → coverage-inclusive base → final clamp), per-finding round-then-sum unpaid-balance rule for `CODE_VIOLATION` accruals, on-time vs late estoppel fee forfeiture with `lifetime_fees_cents` surviving expiry, statutory due date at 23:59:59.000Z, inclusive `valid_through >= closing_date` currency boundary, closed-interval parcel-window adjacency rejection, rush capacity boundary (count == capacity rejected, capacity−1 accepted), all OCC rules (`expected_search_order_version`, `expected_research_task_version` → `ERR_STALE_VERSION`/412), both SoD checks, and every state-machine cascade including delivery voiding/supersession and claim release on cancellation.

**Hard-contract reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs/query params: 94 required, 94 present, 0 missing
- Status: PASS

Rule coverage check:
- validations[] priority ordering: 10 categories expressed in ordered prose (§2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + occ_field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 5 machines / 33 transitions fully expressed with preconditions + side effects, 0 missing
- calculations[]: 9 checked, 9 expressed in precise prose (constants 25000/100000/10×/0.10/25000000 embedded), 0 missing
- validations[] conditions: all 28 error IDs matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults (rush_daily_capacity 5, rush_surcharge_cents 0, supports_rush true, extended_coverage false, renewal_count 0, findings_recorded false) and computed-field semantics reconstructible, 0 missing
- sibling-branch symmetry: on-time vs late receipt, 4 cancellation paths, 3 record-findings branches rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 389
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 47 state/enum values, 5 role names, and the verbatim §2.2 block verified present.

## Step 5: Generate Unit Tests — 2026-08-14T01:49:48.000Z

Generation complete and fully audited. Final state:

## Deliverables

**`/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/test_helpers/`** (9 modules):
- `types.py` — 5 status/machine enums + 9 entity TypedDicts (all entities carry the full common set per PRD §2.5; nullables typed `Optional`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (38 endpoints + clock)
- `api_errors.py` — all 28 error IDs with the §5 HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions (nullables checked only when present)
- `factories.py` / `constants.py` — input-only payload factories; liability-cap constants (25000/100000/×10/10%), MAX_CLAIM 25000000, clock default, Config A department table, canonical findings
- `test_users.py` — all roles are `identity: opaque`, so shared `TEST_USERS` constants plus `make_*_headers(user_id)` builders for ownership/SoD threading; `HEADERS_WITHOUT_ROLE` for the missing-header test
- `fixtures.py` — 5-tier composite helpers: `setup_config_a` → `setup_identified_order` → `setup_research_complete` → `setup_in_verification` → `setup_ready_for_delivery` → `setup_with_ready_delivery`/`setup_delivered`; verify totals are read back from the server so payoff verification always matches

**`test_suite/`** — `conftest.py` + 16 files, **89 test functions (90 collected)**.

## Audit results (all green)
- **Coverage**: 18/18 difficulty instances × ≥2 tests; 53/53 non-stub corner instances × ≥1 test; 15 `excluded_because` stubs verified to resolve to real difficulty instances and not translated; zero phantom/untagged tests.
- **Citations**: 123 quoted PRD sentences all survive a literal grep of `PRD.md`; every docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` line as its last line.
- **Hygiene**: pytest collection clean; no `skip`/`skipif`/`xfail`; no scaffold vocabulary in comments/docstrings.

## PRD-first adjudications (gaps left as gaps, never weakened into the suite)
1. **Literal `version == 1` assertions dropped** — PRD §2.5 pins only "increments by exactly 1", never the initial value; versions are asserted relatively (captured + 1) in the OCC tests instead.
2. **`confirmed_task_discrepancy_reopens_task_and_reverses_fees`** — the instance's order-revert (`DELIVERED`→`RESEARCH_IN_PROGRESS`) and delivery-`SUPERSEDED` assertions were omitted: PRD §3.8 scopes the DELIVERED-order cascade to "a confirmed post-delivery `MISSED_ITEM`", and this instance files `BALANCE_MISMATCH`. The PRD-covered claims (task reopen, fee/payoff reversal to 21000/56500) are asserted by two tests.
3. **`summary.latest_delivery_status`** asserted via `.get() is None` (PRD doesn't pin null-vs-omitted when no delivery exists); pre-completion `fee_charged_cents == 0` sub-assertion dropped from the complete-from-PENDING test (PRD defines the fee only at completion).
4. **`ERR_INVALID_REQUEST` tests kept** (missing parcel, bad `order_class`, RUSH missing `service_date`) — the error is named in PRD prose with trigger conditions and is the catalogue's only malformed-body error, so the outcome is uniquely derivable.

## Step 6: Generate Implementation — 2026-08-14T01:49:48.000Z

Implementation complete and verified. All files live in `/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/workspace/implementation/`:

**Files produced**
- `start.sh` — guarded install (skips `pip install` when flask is importable), `exec python3 app.py` in foreground
- `app.py` — Flask entry point, blueprint registration, envelope-shaped error handlers for ApiError/404/405, binds `0.0.0.0:$PORT` (default 10000), threaded
- `db.py` — empty-on-boot in-memory stores, logical clock fixed at `2026-08-01T00:00:00Z` (never wall-clock), common-field stamping (`id`/`created_at`/`updated_at`/`version`), monotonic insertion seq for tie-broken ordering
- `errors.py` — full 28-error catalog with exact IDs/statuses, `MAX_CLAIM_CENTS = 25000000`
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — `X-User-ID`/`X-User-Role` validation (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), role gating (403 `ERR_FORBIDDEN_FOR_ROLE`)
- `helpers.py` — body/field validators, strict ISO date/instant parsing, clamped `limit`/`offset` pagination, `created_at`-ASC + insertion-order sort
- `services.py` — all 9 calculations (per-finding ROUND_HALF_UP accrual before summation; live-recomputed order totals; pinned 5-step liability cap with `Decimal`; statutory due at 23:59:59.000Z; half-open statute windows; closed-interval parcel overlap; rush capacity boundary), all cascades (cancel, revert-to-research, expiry/overdue sweep, discrepancy-resolve triple cascade), and per-entity serializers
- `routes_*.py` — all 48 endpoints across clock, jurisdictions/statutes/departments/associations, search-orders (incl. OCC-guarded PATCH, summary), research-tasks (OCC-guarded record-findings), estoppels (place/renew/receive/cancel), discrepancies (file/start-review/resolve), deliveries (create/deliver/acknowledge)

**Key design decisions**
- Order totals (`total_payoff_cents`, `total_fees_cents`, `pending_claims_cents`, `total_liability_cents`) are recomputed live from child states in the serializer, eliminating drift; `version` is still bumped on every cascade that touches the order (PATCH pinned to exactly +1 per the PRD).
- Validation pipeline follows PRD §2.8 priority: auth headers → role → existence → state → ownership → SoD → referential → temporal → business → fiscal, with OCC (`ERR_STALE_VERSION` 412) checked after ownership and malformed-body (`ERR_INVALID_REQUEST` 400) checked at the body-shape stage.
- No seeding anywhere; store is empty on every fresh process.

**Verification performed** — exercised end-to-end via Flask test client and real `start.sh` boots: full happy path (identify → findings with 133.5×7=935 half-up accrual → complete → estoppel place/receive → submit → SoD-guarded verify → delivery with frozen cap snapshot → acknowledge → post-delivery MISSED_ITEM resolve with `min(confirmed, cap)` liability and DELIVERED→RESEARCH_IN_PROGRESS supersede cascade), clock sweeps (OVERDUE, late-receipt fee forfeiture, EXPIRED with pipeline revert, renewal), RUSH capacity boundary + candidate pinning + surcharge, PATCH OCC/ownership/stale-closing revert, cancel cascades from INTAKE and READY_FOR_DELIVERY, discrepancy validation (subject-in-order, claim band, SoD), submit gates (tasks outstanding / estoppel not current / stale-for-closing boundary), and pagination meta. Fresh reboot confirmed empty state.

## Step 7: Run Tests and Iterate — 2026-08-14T01:54:51.000Z

All 8 parallel rounds pass 90/90 with zero failures and zero errors. The stability sweep is clean.

**Summary**

- **Iterations run**: 1 (single 8-round parallel sweep — all rounds green on the first pass)
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**: none
- **Fixes applied to `implementation/`**: none

**Details**: All 8 rounds of `prd-bench-local-run --isolation per-test-server` (90 tests each, ~123s per round, run concurrently) report `passed=90 total=90 failed=0 errors=0`. The prior pipeline work (visible in `worklog.md`) had already produced a PRD-faithful test suite and implementation for `task_1594_municipal_lien_search_estoppel_ordering`; this sweep confirms stability under 8× concurrent load with per-test server restarts — no timing-sensitive or flaky failures surfaced.

Relevant paths:
- Results: `/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/workspace/implementation/results.{1..8}.json`
- Implementation: `/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/workspace/implementation/`
- Test suite: `/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/test_suite/` (16 files, 90 collected tests)
- Test helpers: `/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/test_helpers/`

## Step 8: Finalize PRD — 2026-08-14T01:54:51.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determines every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-14T02:16:04.000Z

All edits are in place and the document structure is intact (no new sections; every change is an in-paragraph insert or revision). Work complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1594_municipal_lien_search_estoppel_ordering/workspace/PRD_COMPLETED.md`

**Size delta:** PRD.md = 256 lines / 42,101 chars → PRD_COMPLETED.md = 256 lines / 47,433 chars (char-delta **+5,332**; line count unchanged — all changes are in-paragraph).

**Counts:** 22 ambiguity-pins, 3 mismatch-revisions (25 edit operations; some shared a paragraph, yielding 22 diff hunks).

### Changes

- **§2.1** — insert — ambiguity — unrecognized role strings and blank/whitespace `X-User-ID` are treated as malformed headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400), not as role-forbidden — `implementation/middleware.py:17-28`
- **§2.3** — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], offset to ≥0); non-integer values fall back to defaults — `implementation/helpers.py:123-135`
- **§2.4** — insert — ambiguity — the clock endpoint accepts any ISO-8601 instant, including behind the current reading (clock can move backward); offset-less timestamps read as UTC — `implementation/routes_clock.py:14-24`, `implementation/helpers.py:107-120`
- **§2.4** — insert — ambiguity — every deadline comparison is between whole calendar dates, never timestamps — `implementation/services.py:230,238`, `implementation/routes_estoppels.py:93-94`
- **§2.5** — insert — ambiguity — `version` starts at 1 on creation — `implementation/db.py:55-62`
- **§2.7** — insert — ambiguity — exhaustive list of child events that advance the parent order's `version` (task completion, estoppel receipt, estoppel-expiry sweep, discrepancy filing/resolution, delivery release); all other child mutations (findings writes, mark-unreachable, estoppel place/cancel, delivery create/acknowledge, start-review) leave it unchanged — `implementation/routes_tasks.py:89,104-107,126`, `implementation/routes_estoppels.py:70,109-111,125`, `implementation/services.py:236-245`, `implementation/routes_discrepancies.py:96,153-156`, `implementation/routes_deliveries.py:91-93,111-112`
- **§2.7** — insert — ambiguity — missing or non-integer OCC version field is `ERR_INVALID_REQUEST` (400) — `implementation/routes_orders.py:181-186`, `implementation/routes_tasks.py:68-73`
- **§2.8** — insert — ambiguity — pinned pipeline positions for body-shape validation (`ERR_INVALID_REQUEST`: after role on creations; after the path resource's existence+state guard on resource endpoints, with identify-jurisdiction as the lone exception validating the body first) and for the OCC check (after ownership/SoD, before referential); absent/unparseable JSON body treated as `{}`, non-object body is `ERR_INVALID_REQUEST` — `implementation/helpers.py:14-21`, `implementation/routes_orders.py:172-224,262-276`, `implementation/routes_tasks.py:61-80`
- **§3.1** — revise — mismatch — jurisdiction `code` uniqueness and two-letter `state_code` are not server-enforced (recorded as supplied; any non-empty string accepted) — `implementation/routes_reference.py:35-41`
- **§3.1** — insert — ambiguity — jurisdiction deactivation is idempotent (already-INACTIVE → 200, no mutation) — `implementation/routes_reference.py:73-76`
- **§3.1** — insert — ambiguity — department deactivation is likewise idempotent — `implementation/routes_reference.py:217-220`
- **§3.1** — insert — ambiguity — association registration with no statute covering the clock date fails `ERR_NO_STATUTE_IN_FORCE` — `implementation/routes_reference.py:236-241`
- **§3.1** — insert — ambiguity — all section monetary/day-count fields must be non-negative integers (`ERR_INVALID_REQUEST` otherwise) — `implementation/routes_reference.py:38,88-90,159-160,232-233`
- **§3.2** — insert — ambiguity — `service_date`/`jurisdiction_id` supplied on a STANDARD creation are ignored — `implementation/routes_orders.py:62-73`
- **§3.3** — insert — ambiguity — fixed rejection sequence at identification: order INTAKE state → rush-candidate equality → jurisdiction ACTIVE → statute coverage → association belonging — `implementation/routes_orders.py:272-296`
- **§3.4** — insert — ambiguity — no sign constraint on `amount_cents`/`daily_accrual_cents`/`days_outstanding`; empty `findings` array accepted (zero balance, zero violations) — `implementation/routes_tasks.py:30-49,74-88`
- **§3.4** — insert — ambiguity — `fee_charged_cents` reads zero before completion and after any reopen (derived from status) — `implementation/services.py:42-49`
- **§3.5** — revise — mismatch — a missing/non-integral/non-positive quote is `ERR_INVALID_REQUEST` (400); only a positive quote above the pinned cap is `ERR_QUOTE_EXCEEDS_STATUTORY_CAP` (PRD previously routed all out-of-band quotes to the latter) — `implementation/routes_estoppels.py:44-56`
- **§3.6** — insert — ambiguity — summary semantics: `task_counts` keyed by all five task statuses, `estoppel_count` counts all statuses, `open_discrepancy_count` counts OPEN+UNDER_REVIEW, `latest_delivery_status` = most recently created delivery's status or null — `implementation/routes_orders.py:148-165`
- **§3.7** — insert — ambiguity — update body must name at least one of `closing_date`/`association_id` and `closing_date` must not be null (`ERR_INVALID_REQUEST`) — `implementation/routes_orders.py:187-198`
- **§3.7** — revise — mismatch — association change spawns the fresh DRAFT only once the order has an identified jurisdiction (INTAKE changes record only; the draft spawns at identification); clearing to null spawns none; naming the current association is a no-op; the jurisdiction-mismatch check applies only post-identification — `implementation/routes_orders.py:211-245,306-307`
- **§3.7** — insert — ambiguity — force-resolved (VOID_ORDER_CANCELLED) discrepancies record no `resolved_by_user_id` (stays null) — `implementation/services.py:211-216`
- **§3.8** — insert — ambiguity — `confirmed_liability_cents` starts at zero at filing — `implementation/routes_discrepancies.py:91`
- **§3.8** — insert — ambiguity — resolution records a supplied `confirmed_amount_cents` whatever the outcome and leaves `confirmed_liability_cents` at zero unless a cascade sets it — `implementation/routes_discrepancies.py:149-151`
- **§3.8** — insert — ambiguity — liability cap taken from the most recently created DELIVERED/ACKNOWLEDGED delivery, treated as zero when none stands in either status — `implementation/routes_discrepancies.py:165-170`
- **§3.8** — insert — ambiguity — `total_liability_cents` defined as the running sum of `confirmed_liability_cents` over RESOLVED discrepancies — `implementation/services.py:83-87`
- **§4** — insert — ambiguity — unknown paths and unsupported methods answered `ERR_NOT_FOUND` (404) in the standard envelope — `implementation/app.py:38-44`

**Verification notes:** All calculations (per-finding round-half-up-then-sum, five-step liability cap), state machines, sweep boundaries (due date/valid_through inclusive boundary days), rush capacity band, closed parcel window, and the endpoint/role/error catalogs in the PRD already matched the implementation exactly and were left untouched.
