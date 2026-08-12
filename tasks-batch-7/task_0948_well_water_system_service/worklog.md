# Worklog — task_0948_well_water_system_service

Scenario (verbatim from user):
```
948. Well & Water-System Service (private): well/pump profile & inspection, service (pump/pressure-tank/filtration) & quote, water-test & treatment recommendation, emergency (no-water) dispatch, recurring maintenance & salt/filter, permit coordination, warranty/callback, billing
```
Difficulty request: **harder than Expert level**.

## Step 1: Create task directory — 2026-08-09T10:28:30.000Z

Created `tasks/task_0948_well_water_system_service/` and `tasks/task_0948_well_water_system_service/workspace/`.
Host at start: 8 cores, load ~1.0, 5 co-tenant `claude` sessions active (task_0947 in progress by another session) → Step 7 sweep concurrency must be capped/serialized.

## Step 2: Generate scaffold — 2026-08-09T11:32:00.000Z

Scaffold-gen subagent was spawned with the "beyond Expert" difficulty phrased as a **generation parameter**, never as a gate to evaluate (per the known failure mode where a difficulty *line* halts the orchestrator). It wrote all three files but **stalled mid-stream before returning its summary** (474k subagent tokens, 71 tool uses, 68 min). All three files were verified complete on disk rather than regenerated.

Measured from disk (not estimated):

| §1.5 endpoints | §1.1 entities | §1.2 state machines | §1.3 calculations | §1.4 validations | §1.6 errors | §1.7 roles | ladder rungs | global constants |
|---|---|---|---|---|---|---|---|---|
| **121** | **21** | **16** | **46** | **74** | **93** | **7** | **68** | **44** |

- complexity_profile: primary `workflow_orchestration` × secondary `pricing_engine`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; topology `graph`; SM shape `parallel`; role model `segregation_of_duties`.
- **Two structurally different pipelines share ONE derivation ladder** — Pipeline S (scheduled/quoted: Inspection → Quote DRAFT/PRICED/SENT/APPROVED → WorkOrder) and Pipeline E (emergency no-water dispatch), diverging on authorization order, surcharge tiers, and permit prerequisites.
- `gate_precedence` block declares a **global total order of 9 write gates** (G1_AUTH → G2_ROLE → G3_PATH_EXISTENCE → G4 → G5 → G6 → G7_OCC → G8 → G9), each mutating endpoint naming its applicable subsequence; GETs run G1/G2/G3/G4/G8_QUERY only. A `mutate_then_reject` sub-block is declared.
- `design_notes.domain_seams`: **15 seams**. `design_notes.friction_points_not_prejudged`: **11 friction points** recorded with both readings named, un-adjudicated (downstream steps decide).
- Constants: all 44 `global_constants` carry values; the 11 remaining symbolic `*_DAYS/_PCT/_FEE` names are mapping-table keys or enum members whose tables are declared inline (verified by grep). **No undeclared constant.**
- YAML: all three files `yaml.safe_load` clean.
- Official `scaffold_lint.py`: **clean lint** — all §1.8/§1.9 calls conform to §1.5, all §1.1 FKs have reverse-reachability in §1.5.

### Step 2b: §1.9 corner-design breadth expansion (bounded follow-up subagent)

The stalled run left §1.9 badly under-covering the surface it must probe (3 of 74 validations, 3 of 121 endpoints, 10 of 93 errors, 6 of 46 calculations; `rbac` / `cross_cutting_complexity_layers` / `consistency_model` sections absent entirely). A **fresh, bounded** subagent extended only `SCAFFOLD_CORNER_DESIGN.yaml`.

Verbatim summary:

> `SCAFFOLD_CORNER_DESIGN.yaml` extended from 52 → 102 instances; `SCAFFOLD.yaml` and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` untouched.
>
> **New instances: 50, by section** — calculations +9 (→15), validations +10 (→13), endpoints +7 (→10), errors +9 (→19), rbac +7 (new element), cross_cutting_complexity_layers +6 (new element), consistency_model +2 (new element); entities/state_machines unchanged at 11/19.
>
> **Final total: 102 instances (counted), 3 `excluded_because:` stubs** (all pre-existing; all three cite `difficulty_instance` names that resolve). All 52 original instances verified present and unmodified.
>
> **Coverage closed** — Error codes asserted in an `assert:` line: **93/93** (was 84/93); the 9 previously-unasserted were `ERR_UNAUTHENTICATED`, `ERR_UNAUTHORIZED`, `ERR_ACTOR_SCOPE_VIOLATION`, `ERR_CONFIRMATORY_SAME_OFFICER`, `ERR_TREATMENT_RECOMMENDATION_INVALID_STATE` and all four `ERR_STALE_*_VERSION`. Calculations named in `grounds:`: **46/46** (was 39/46). Validation priorities named in `grounds:`: 46/74 (was 30/74). Six instances are pure ERROR PRECEDENCE: G1>G2/G3, G2>G3, G3>G5>G8, G5>G9-fiscal, G7-OCC>G8>G9, G4>G9, plus within-G6 ordering (priority 22 > 23 > 25) and within-G9 ordering (55 > 56) — each names the loser it beat in `distinguishing_aspect`. Exact-boundary pairs added: pagination 1/100 vs 0/101/-1; salt 300.0 vs 340.0 and 40.0 vs 39.9; filter change 29 vs 30 days; quantity 50 vs 51; schedule window end==start vs +1min; hold time exactly 30.0 h; clock equal-instant vs −1 s; inspection validity day 365 vs 366; callback window day 90 vs 91 (LABOR) with PART still open; markup bands 25000/25001 and 100000/100001; duty-cycle ratio 3.00/6.00/6.01; severity 59/60/100-cap; shared-well 4 parties vs 5.
>
> **SCAFFOLD.yaml §1.5 changes: None.** Every chain resolved at rung 1 (compose existing endpoints). No business endpoint and no `/_<name>` test-driving endpoint was added.
>
> **Reachability notes found while writing chains:**
> - *No id-returning read for cascade-created children.* `WarrantyCoverage`, the confirmatory child `WaterTest`, `Invoice` and `MaintenanceVisit` are never returned by the call that creates them; their ids are only obtainable via the filtered/sub-resource lists with a `$.data[0].id` capture. Workable, but every warranty/callback/invoice chain must include an extra list read.
> - *`Quote.version` is not observable from the line-add response.* `POST /quotes/{id}/lines` returns `QuoteLine`, so any multi-line chain must interleave `GET /quotes/{id}` to re-read the version for the next `expected_quote_version`. Same shape for `MaintenancePlan` after a salt delivery.
> - *`evaluate-compliance` at exactly `next_due_at` is under-specified* — the scaffold pins the latch on `clock > next_due_at` (strict) but does not say whether a non-qualifying call 200s as a no-op or errors. Planned exact-boundary instance dropped rather than guessed.
> - *`quantity: 0` on a quote line is ambiguous* between priority-30 `ERR_VALIDATION` and priority-33 `ERR_NEGATIVE_QUANTITY` (0 is not strictly negative, and the "at least 1" rule is only mentioned in priority 58's note). The quantity-boundary instance asserts 50 / 51 / −1 only.
> - *Severity 30 is reachable only via `NON_WELL_CAUSE`* (all other cause values leave a remainder that is not a multiple of 3 against the household/outage point steps), which would confound the LOW/MID edge with the SEAM-05 surcharge collapse — so the severity instance uses the 59/60 MID/HIGH edge plus the 100 cap instead.
>
> **Lint verdict (verbatim):** clean lint — §1.5 endpoints 121, §1.1 entities 21, §1.8 instances 23, §1.9 instances 99 (102 minus 3 stubs), calls scanned 1787; all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
>
> Independently verified beyond the lint: 125 instance names unique across both design files, zero unbound `${var}` placeholders across all 102 instances, `yaml.safe_load` clean.

**Test-producing instances entering Step 5: 23 (§1.8) + 99 (§1.9) = 122.**

## Step 3: Copy shared files — 2026-08-09T12:17:00.000Z

`cp ./INSTRUCTION.md tasks/task_0948_well_water_system_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-09T12:36:00.000Z

Verbatim subagent summary:

> The PRD is complete and verified.
>
> **Output:** `workspace/PRD.md` — **1274 lines**.
>
> **Section list** — §1 Introduction · §2 Global Specifications: 2.1 Actors/Identity/RBAC · 2.2 API Response Structure (verbatim, byte-identical — verified by diff) · 2.3 Pagination and List Ordering · 2.4 Logical Clock and Rendering of Instants · 2.5 Common Resource Properties and `version` Semantics · 2.6 The Nine-Gate Global Write Order · 2.7 Payload Validation and Closed Routing of Enum Errors · 2.8 Optimistic Concurrency Control · 2.9 Money, Rounding and Evaluation Order · 2.10 Boundary Conventions · 2.11 Writes That Persist Behind an Error Response · 2.12 Two Conserved Quantities · 2.13 Segregation of Duties · 2.14 Tensions Deliberately Left Open · §3 Business Logic: 3.1 Register (accounts/properties/wells/shared wells/technicians/catalog) · 3.2 Inspection + duty-cycle cascade · 3.3 Water quality · 3.4 Treatment recommendation + softener sizing · 3.5 The Costing Ladder · 3.6 Scheduled pipeline · 3.7 Permits + mandated-alternate cascade · 3.8 Emergency pipeline · 3.9 Work orders + 8-hop completion cascade · 3.10 Recurring maintenance · 3.11 Invoicing/splits/ledger · 3.12 Warranty, callbacks, remedies · §4 Endpoint Definitions (4.1–4.22, one block per endpoint: roles, success code, response entity, request fields with defaults, error list) · §5 Error Code Catalogue
>
> **Machine-verified counts**
> - **Endpoints: 121/121** as `(method, path)` pairs — zero missing, zero extra (script-diffed against `SCAFFOLD.yaml`).
> - **Error codes: 93/93** named in prose. All 93 also appear in §1–§3 prose (not only in §4/§5).
> - Field-name coverage: 196/196 required identifiers (176 entity fields + 109 body fields + 21 path params, deduped) present verbatim in backticks — 0 missing.
> - Enum/state value coverage: every `one of …` member, every state-machine state, every role name — 0 missing.
> - §3 path purity: 1419 backtick tokens scanned in §3, **0** starting with `/`, 0 bare HTTP methods, 0 method+path.
>
> **Required items and where they live**
> - **9-gate global write order + lowest-numbered-gate rule: §2.6**, with worked precedence examples and the two intra-gate orderings (write-off checks billing before fulfilment; duplicate-share before share-sum). Read endpoints run G1–G4 + G8_QUERY only.
> - **Timestamp rendering: §2.4** — exactly three fractional digits with `Z`, e.g. `2026-05-01T00:00:00.000Z`; explicitly states client-supplied instants are **re-rendered canonically, never echoed as sent**; nulls render as `null`; comparison is instant-wise, not string-wise.
> - **Enum-routing closed lists: §2.7** — closed `iff` list of the 12 body fields routing to `ERR_INVALID_ENUM` with all members, plus explicit "no other body field routes here" and the named exclusion of the four jurisdiction-code fields (→ `ERR_VALIDATION`). Closed lists also given for `ERR_INVALID_TIMESTAMP`, `ERR_NEGATIVE_QUANTITY`, `ERR_INVALID_DATE_RANGE`.
> - **`mutate_then_reject` (L60/L61/L62): §2.11**, stated as durable writes that persist behind the error, positioned at G9 with the explicit "if G1–G8 fails, nothing is written" contrast; re-stated at each site (§3.3, §3.6, §3.12) and flagged in the §4 entries.
> - All 44 `global_constants` carried with values (§2.10 roster + in-context use); all mapping tables reproduced in full (labour base rates, band multipliers, markup bands, trip-fee zones, cause points, surcharge bands, membership credits/caps, jurisdiction tiers, permit base fees, scope multipliers, scope→tier table, base intervals, media reductions, filter intervals, softener capacity table).
>
> **The 11 friction points — all carried forward un-adjudicated (§2.14)**
> 1. FR-01 recommendation-expiry re-anchoring — both readings stated; shared ground (anchored on a *sample* instant, never `created_at`) asserted. Un-adjudicated.
> 2. FR-02 `NON_WELL_CAUSE` and the trip fee — both readings stated; only the surcharge-collapse agreement asserted. Un-adjudicated.
> 3. FR-03 shared-well split scope vs. surcharge — both readings stated; parts+labour split agreed. Un-adjudicated.
> 4. FR-04 emergency repair clearing the overdue latch — both readings stated; "interval recomputation never clears it" agreed. Un-adjudicated.
> 5. FR-05 re-approval after a cost-reducing supersede — both readings stated; "a raise requires re-approval" agreed. Un-adjudicated.
> 6. FR-06 term of a warranty-replacement coverage — both readings stated; mint + supersede agreed. Un-adjudicated.
> 7. FR-07 inspection staleness re-check at scheduling — both readings stated; checked-at-approval agreed. Un-adjudicated.
> 8. FR-08 governing membership tier mid-ticket — both readings stated; `membership_tier_at_intake` latched-and-never-rewritten agreed. Un-adjudicated.
> 9. FR-09 chemical exceedance vs. bacteriological clearance — both readings stated. Un-adjudicated.
> 10. FR-10 `last_service_date` naming — the **pinned computational behaviour** (advances on any visit kind; salt-only slides `next_due_at` while `OVERDUE` persists) is stated in §3.10 as required for determinism; the *naming* question is explicitly left open.
> 11. FR-11 loyalty discount self-eligibility — the **pinned evaluation order** (threshold tested against the pre-discount pre-tax figure) is stated in §3.11; the commercial reading is explicitly left un-adjudicated.
>
> **Scaffold inconsistencies / under-specifications encountered (not papered over)**
> 1. **Shared-well 100.00 identity — three-way contradiction.** `endpoints[].side_effects` and rung L67 both say ACTIVE shares "must total exactly 100.00 after the write", but validation priority 68 says they must not *exceed* 100.00 with "under-allocation permitted at creation". I followed validation 68 (it carries the error id, and `shared_well_billing_split_cents`'s own input_set assumes under-allocation is reachable, otherwise its fallback branch is dead code). Stated in §3.1 and §3.11.
> 2. **Validation priority order vs. gate order.** `validations[].priority` is not gate-monotone: priority 62 (`ERR_WARRANTY_ALREADY_SUPERSEDED`) is tagged G5 yet sits after G9 items 37–61, and priority 12 (fulfilment) precedes priority 13 (billing) while its own `applies_to` text says write-off checks fulfilment *after* billing. I made the gate order governing (the block calls itself GLOBAL/TOTAL), with priority ordering *within* a gate, and stated the write-off billing-first rule explicitly in §2.6.
> 3. **`ERR_MAINTENANCE_VISIT_NOT_FOUND` is absent from G3's error list** though the error exists and `GET /maintenance-visits/{maintenance_visit_id}` needs it. Included anyway.
> 4. **`ERR_PREAUTH_CAP_EXCEEDED` basis is under-specified** — "cumulative posted parts plus labor" at a moment when `labor_charge_cents` is still 0. I pinned it as posted extended prices (including the row being posted) plus the work order's current `labor_charge_cents`.
> 5. **Multi-invoice shared-split field semantics are under-specified** — step 11 defines only per-account *totals*. I pinned `total_cents` and `shared_split_pct` as the per-share fields and the component subtotals as carrying the undivided work-order figures; noted here because a test could reasonably assert either.
> 6. **InvoiceLine emission for zero-valued lines is unstated.** I pinned: PARTS one per POSTED entry, LABOR and TAX always, DISPATCH_SURCHARGE/TRIP_FEE only on the emergency pipeline, PERMIT_FEE/WARRANTY_CREDIT/LOYALTY_DISCOUNT only when non-zero.
> 7. **`Account.lifetime_invoiced_cents` description drifts from its transitions** — the field says "every invoice that has *ever* reached ISSUED", but the void transition subtracts from it. I described the transition arithmetic and dropped the "ever" phrasing.
> 8. **Jurisdiction codes are `type: string` with a `one of` constraint**, so `ERR_INVALID_ENUM`'s "enum-typed body field" scope does not cover them. I routed them to `ERR_VALIDATION` and said so explicitly as a named exclusion — the alternative reading is live, and this is the single highest-risk pin in the document.
> 9. **`MAX_WORK_ORDER_DURATION_MINUTES` (720) is declared but referenced by no calculation**; it coincides with the 720 ceilings on `estimated_labor_minutes` and `actual_labor_minutes`, and I carried it as that ceiling.

Orchestrator note: item 8 (jurisdiction codes → `ERR_VALIDATION`) is flagged as the highest-risk pin; it is carried into Step 5/6 as a live divergence to watch, not as settled.

## Step 6: Generate implementation — 2026-08-09T13:16:00.000Z

Launched **concurrently with Step 5 in a single assistant message**, so `test_suite/` and `test_helpers/` did not exist at spawn time (physical isolation). Step 6 finished first, at 13:16, with Step 5 still writing — the reverse of the dangerous ordering, and impl-gen was under an explicit standing ban on reading the test dirs.

**Orchestrator-run route gate (independent of the subagent's own claim):** booted `app.py` in-process, enumerated `url_map`, and diffed `(method, path)` **pairs** against `SCAFFOLD.yaml` §1.5 — **121 impl = 121 scaffold, symmetric difference empty in both directions.** Pairs, not paths: a path-only diff collapses same-path/different-method endpoints and prints "clean" while endpoints are missing.

Verbatim subagent summary:

> The implementation is complete and verified. Final report:
>
> ## Module layout (all under `workspace/implementation/`, 4,264 lines total)
>
> | File | Lines | Role |
> |---|---|---|
> | `app.py` | 106 | Flask app, route registration from the shared registry, defensive bind + serve |
> | `core.py` | 688 | Errors (93-code catalogue), logical clock, in-memory `Store`, envelope, canonical instant rendering/parsing, G8 field spec, pagination/filters, **the nine-gate pipeline** |
> | `calc.py` | 399 | All 46 calculations + every named constant from §2.10 |
> | `serialize.py` | 166 | Per-entity JSON representation; the single place instants are rendered |
> | `common.py` | 167 | G4 scope resolvers, G9A FK resolution, G5 gate factories, shared cascade fragments |
> | `cascade.py` | 289 | 8-hop completion cascade + 11-step invoice construction + shared-well split |
> | `r_register.py` | 469 | clock, accounts, properties, wells, shared-well agreements, technicians, parts catalog (29 endpoints) |
> | `r_field.py` | 384 | inspections, water tests, treatment recommendations (16) |
> | `r_quote.py` | 477 | quotes, quote lines, permits (21) |
> | `r_emerg.py` | 218 | emergency tickets (11) |
> | `r_wo.py` | 579 | work orders, parts consumption, warranty, callbacks (24) |
> | `r_maint.py` | 175 | maintenance plans + visits (12) |
> | `r_bill.py` | 137 | invoices + invoice lines (8) |
>
> ## Completeness gate
>
> **Counted `(method, path)` route pairs: 121.** Symmetric difference against the 121 pairs parsed out of PRD §4 is **empty**. `ast.parse` succeeds on all 13 `.py` files; `bash start.sh` boots and serves. Flask's default `/static/<path>` route is disabled (`static_folder=None`) so it does not inflate the count.
>
> Three further automated cross-checks against PRD §4, all clean: **201-vs-200 status codes** (18 creates, symmetric diff empty), **role lists** (121/121 exact match), **filter parameter sets + pagination flags** (21 filtered lists, 0 mismatches).
>
> ## 1. Timestamp three-case adjudication (verified live)
>
> | case | input | rendered |
> |---|---|---|
> | (a) server-computed (`created_at`) | logical clock | `2026-05-01T00:00:00.000Z` |
> | (b) client-supplied with fraction | `2026-05-02T09:00:00.123456Z` | `2026-05-02T09:00:00.123Z` |
> | (c) client-supplied without fraction | `2026-05-02T09:00:00Z` | `2026-05-02T09:00:00.000Z` |
> | (c′) offset form | `2026-05-02T11:00:00+02:00` | `2026-05-02T09:00:00.000Z` |
>
> All three render identically in canonical form through the single serializer `core.iso` (core.py:192), which every field in `serialize.DATETIME_FIELDS` passes through. Sub-millisecond precision is retained for arithmetic — proved live: a chemical panel analysed at exactly `sample+336h` with `.123456` micros stays valid while `+336h+1ms` lands in `INVALID_HOLD_TIME`. Every internal comparison is instant-wise (`datetime` objects); no string comparison of timestamps exists anywhere.
>
> ## 2. Enum routing — member-for-member
>
> 19 `enum=` sites, exactly the closed §2.7 list: `membership_tier` ×2 (account create, account PATCH) · `well_type` ×1 · `tier` ×1 · `status` ×4 (technician create, technician PATCH, part create, part PATCH) · `category` ×1 · `media_kind` ×1 · `panel_type` ×1 · `scope` ×4 (quote, permit, work order, remedy work order) · `quoted_technician_tier` ×1 · `cause_class` ×1 · `complaint_class` ×1 · `decision` ×1. No other body field routes there. The five jurisdiction-code fields (`billing_jurisdiction_code`, `jurisdiction_code` on property / well / permit, `home_jurisdiction_code`) use `one_of=` → **`ERR_VALIDATION`**, verified live. Filters are never enum-validated (unknown filter value ⇒ empty page, `total_count` 0).
>
> ## 3. Gate pipeline
>
> Single shared implementation in `core.run_endpoint` (core.py:~640). Every endpoint is a declarative `Endpoint` spec; the runner executes G1_AUTH → G2_ROLE → G3_PATH_EXISTENCE → G4_SCOPE → G5 → G6 → G7_OCC → G8 (+`g8_post`) → handler(G9). Reads take the `G1–G4 + G8_QUERY` branch only. Handlers contain **only** G9 logic. Intra-gate orderings implemented: write-off checks billing before fulfilment (`r_wo._write_off_gate`); duplicate share before share-sum (`r_register.create_share`). Within G9B I follow the **PRD §4 per-endpoint error-list order**, which I verified is exactly gate order on every entry — §2.6 itself defers to it ("checks are evaluated in the order the sections below give them"). Verified live: G1>all, G2>G5, G4>G8, G7>G8.
>
> ## 4. Mutate-then-reject rungs
>
> `ApiError(persist=True)` causes `ctx.flush()` (version/`updated_at` bumps) before the error response; nothing is rolled back. Three sites, all verified live:
> - `r_field.confirmatory_result` → `ERR_RETEST_CONFIRMED_POSITIVE` (child row created, parent `CONFIRMED_POSITIVE`, `confirmed_by_user_id` stored, well `UNSAFE`/`CONFIRMED_COLIFORM`)
> - `r_quote.approve_quote` → `ERR_QUOTE_LINE_YIELD_EXCEEDED` (lines `SUPERSEDED_BY_YIELD`, quote `REVISION_REQUIRED`)
> - `r_wo.raise_callback_claim` → `ERR_CALLBACK_OUT_OF_WARRANTY` (claim durably `REJECTED_OUT_OF_WARRANTY`, `claim_count`/`callback_attempt_count` up, `callback_eligibility` `EXPIRED`)
>
> ## 5. Bind strategy (EADDRINUSE)
>
> `app.py:81 _bind()` — bounded retry loop (6 s cap, 50 ms sleeps) around `socket()`/`SO_REUSEADDR`/`bind()`/`listen(256)`; the already-bound socket is handed to `werkzeug.serving.make_server(..., threaded=True, fd=sock.fileno())` at `app.py:102`. `start.sh:8` uses `exec python3 app.py`, so no intermediate shell can squat the port. **12 consecutive kill→relaunch cycles all served within the window, 0 failures.** A global `RLock` around `run_endpoint` keeps the threaded server's in-memory state consistent.
>
> ## 6. Verified worked examples
>
> Both PRD §3.11 worked totals reproduce exactly: emergency/`NONE` → **146148**, same job at `PREMIER` → **126148** (credit unlocks at severity 60, loyalty correctly *not* applied because the pre-discount figure falls to 121508). Quote §3.6 total **91086**. Softener 30.0 gpg / household 5 → 78750 / `CAP_80000` / 77.1. Travel-buffer geometry (11:00 conflicts, 11:45 does not), per-well daily cap, ledger identity restored exactly on void, inventory conservation on `IN_PROGRESS` cancel, hold-time right-closure, zone and duty-cycle band boundaries.
>
> ## Reachability audit — claims to verify downstream
>
> Each is a **hypothesis**, not a fact:
>
> 1. **`SCHEDULED → HELD` is dead, and with it `hold_reason = PERMIT_CONDITION_REVISION` and the `HELD → SCHEDULED` return path.** CASCADE-C-2 hop 4 fires only when the permit approval takes the quote *out of* `APPROVED`; but a work order can only be created from an `APPROVED` quote and creating it moves the quote `APPROVED → CONSUMED` (terminal). So whenever a work order exists on the quote, the quote is `CONSUMED` at permit-approve time and hop 4's precondition is false. *Empirically observed*: smoke run printed "permit cascade: quote status CONSUMED" with the work order still `SCHEDULED`. **Verify by reading `r_wo.create_work_order` (quote→CONSUMED) against `r_quote.approve_permit` hops 3–4.**
> 2. **`ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE` on `POST /invoices/{id}/issue` is unreachable.** An invoice exists only as hop 7 of completion, and `COMPLETED` is terminal (`cancel` admits only DRAFT/SCHEDULED/IN_PROGRESS). **Verify by reading `cascade.build_invoices` (sole call site) and `r_wo.cancel_work_order`'s G5 gate.**
> 3. **The `max(surcharge − credit, 0)` floor in `net_dispatch_charge_cents` is arithmetically dead** — the credit is `min(surcharge, cap)`, so the difference is never negative. **Verify by reading `calc.membership_credit_cents` + `calc.net_dispatch_charge_cents`.**
> 4. **The `max(0, …)` floor on `taxable_subtotal_cents` IS reachable**, but only on a remedy invoice where the parts credit applies and the labour credit does not (claim day 91–365) and labour alone clears 200000 (MASTER/WEEKEND 720 min ⇒ 243000): taxable becomes `−loyalty` and floors to 0. **Verify by reading `cascade.build_invoices` steps 5–8.**
> 5. **`ERR_CALLBACK_LIMIT_REACHED` is reachable** only by raising three in-warranty claims against the *same* coverage before approving the third (nothing caps claims per work order until a remedy completes and sets `CONSUMED`). **Verify by reading `r_wo.raise_callback_claim` (no per-coverage intake cap) and `adjudicate_claim` (`claim_count > 2`).**
> 6. **`ERR_INSPECTION_REQUIRED` is reachable** — create a well, create an inspection and never complete it, cite it on a quote, add a `PUMP` line with `rated_gpm ≥ 5.0`. **Verify by reading `common.pump_yield_check` and `r_quote.add_quote_line`.**
> 7. **`ERR_POTABILITY_PENDING_CONFIRMATION` is reachable only in one order** — chemical exceedance first (founding the recommendation), *then* a bacteriological presumptive positive; the reverse order lets the chemical lab-result overwrite `advisory_reason` to `CHEMICAL_EXCEEDANCE`. **Verify by reading `r_field.lab_result` and `accept_recommendation`.**
> 8. **`ERR_SHARED_WELL_SPLIT_INVALID` via the party-count branch alone** needs five shares summing ≤ 100.00 (e.g. five of 0.01); otherwise the sum branch fires first. Both raise the same error, so the distinction is unobservable. **Verify by reading `r_register.create_share`.**
>
> ## PRD silences / contradictions I had to resolve (Step 8/9 work items)
>
> 1. **G9B intra-gate order, quote lines.** §3.6 + §4 give discontinued → quantity → pump-yield; §2.6's category sentence ("safety first … then quantity") and SCAFFOLD priorities 41/42 < 55/58 give the opposite. **Chose §4's error-list order**, because §2.6 explicitly defers ("checks are evaluated in the order the sections below give them") and §4's listing is provably gate-ordered on every endpoint.
> 2. **G9B order, recommendation accept.** §3.4 prose says EXPIRED then POTABILITY; §4 lists POTABILITY then EXPIRED. **Chose §4** (potability first).
> 3. **Quote `/expire` when the 30-day window is still open.** No error is named. **Chose `ERR_QUOTE_INVALID_STATE`** (the only 409 the endpoint lists).
> 4. **`POST /warranty-coverages/{id}/void` with an `APPROVED_WARRANTY` claim standing.** No distinct error. **Chose `ERR_WARRANTY_ALREADY_SUPERSEDED`.**
> 5. **Adjudicate `APPROVE` requires `coverage_state == ACTIVE`** (§3.12) but §4 names no error for it. **Chose not to enforce it** rather than invent an unauthorised error. This is the most likely place a test disagrees.
> 6. **`claim_count` limit comparison.** "has not already been claimed 2 times" vs "a claim_count *beyond* that limit". **Chose `> 2`** (matches SCAFFOLD's `claim_count <= CALLBACK_MAX_PER_COVERAGE` and keeps the 2nd claim approvable).
> 7. **`quantity` minimum on quote lines / parts consumption.** SCAFFOLD says `1 <= quantity <= 50`; §2.7 says G8 "only checks that the quantity is a non-negative integer". **Followed the PRD** — `quantity: 0` is accepted at G8 and there is no later rule refusing it.
> 8. **`new_drawdown_gallons` range** on pressure-tank replacement is unstated. **Applied the entity's 1.0–120.0 constraint** (`ERR_VALIDATION`).
> 9. **Category-specific part attributes.** "required for a PUMP and null otherwise" — **required-when-applicable ⇒ `ERR_VALIDATION`; force-nulled when not applicable** (a `rated_gpm` sent on a `FILTRATION` part is stored as null, not echoed).
> 10. **`part_number` uniqueness** is asserted but has no error code. **Not enforced.**
> 11. **`post_hoc` permit with `work_order_id` null.** **Chose `ERR_POST_HOC_PERMIT_WINDOW_EXPIRED`.**
> 12. **`SharedWellAgreement` terminate** carries `G5_ENTITY_STATE` in SCAFFOLD but no state error exists. **Made it unconditional** (re-terminating succeeds).
> 13. **`evaluate-compliance` on an already-`OVERDUE` plan** — no error listed. **Returns 200 unchanged, no version bump** (the bump is stated only as a side effect of the latch).
> 14. **Bacteriological lab result with `coliform_present` omitted.** **Treated as not-true ⇒ `ANALYZED_NEGATIVE`.**
> 15. **Chemical panel always copies `hardness_gpg` onto the well**, including when null. **Implemented literally**, and the well's `version` rises in every branch except `INVALID_HOLD_TIME` (the only branch §3.3 calls "untouched").
> 16. **Catalog-part `version` at completion.** §3.9's list says "each touched catalog part's version" rises, but §2.12 says completion moves no stock. **Chose not to bump** catalog parts at completion.
> 17. **Well `version` at completion.** Listed unqualified. **Chose to bump unconditionally**, even when no pressure-tank part moved the drawdown.
> 18. **`cancel` from `SCHEDULED`** "releases the technician's window". **Chose to leave `scheduled_start_at`/`scheduled_end_at` stored** (the status change alone removes it from the overlap set); only the HELD transition clears them, as §3.7 states explicitly.
> 19. **Confirmatory child `WaterTest` fields.** Only `parent_test_id`, `panel_type`, `result_status` are pinned. **Chose** to copy well/technician/sample/analyzed/coliform and set `hold_time_valid` true, leaving `recorded_by_user_id` and `confirmed_by_user_id` null on the child.
> 20. **Coverage superseded when several `PART` coverages were minted.** "the newly minted coverage of the same class" is ambiguous. **Chose the first minted `PART` coverage** (entry order).
> 21. **Loyalty-eligibility account on a shared-well split.** The undivided figures are computed once, before the split. **Chose the property's own `account_id`** (the work order's billing account), not the per-share accounts.
> 22. **Invoice lines under a split.** **Chose to construct the full line set per invoice**, each numbered from 1, carrying the undivided amounts — consistent with §3.11's statement that every invoice's subtotal fields carry the undivided figures.
> 23. **`HELD → SCHEDULED` requires "the parent quote is `APPROVED` again"** but names no error. **Not enforced** (and see reachability claim 1 — the path is dead anyway).
> 24. **Quote creation does not require the cited inspection to be `COMPLETED`** — §4 lists no state error, and `ERR_INSPECTION_STALE` at approval covers a non-completed inspection. **Not enforced at creation.**
> 25. **G6 checks that read body instants** (confirmatory retest window/hold time; adjudicate's decision-dependent state gate) run *before* G8 per §4's error order. **Chose to peek the body non-fatally**: an unparseable instant makes the G6 check skip so G8 can answer `ERR_INVALID_TIMESTAMP`; an unrecognised `decision` makes the state gate accept any adjudicable state so G8 can answer `ERR_INVALID_ENUM`.

## Step 5: Generate unit tests — 2026-08-09T13:27:00.000Z

Verbatim subagent summary:

> Test infrastructure and suite generated for `task_0948_well_water_system_service`.
>
> ## Files written
>
> **`test_helpers/`** (2,811 lines) — `__init__.py` 43 · `types.py` 403 · `api_client.py` 643 · `api_errors.py` 202 · `assertions.py` 170 · `constants.py` 117 · `factories.py` 176 · `test_users.py` 88 · `fixtures.py` 969.
>
> **`test_suite/`** (7,933 lines, 17 files): `conftest.py` (63), `test_01_register_and_defaults` (573), `test_02_inspection_and_duty_cycle` (360), `test_03_water_quality` (534), `test_04_treatment_recommendations` (576), `test_05_quote_pricing` (530), `test_06_quote_lifecycle` (308), `test_07_permits` (540), `test_08_emergency_pipeline` (452), `test_09_work_order_scheduling` (472), `test_10_parts_and_execution` (453), `test_11_completion_cascade` (556), `test_12_warranty_and_callbacks` (600), `test_13_invoicing_and_ledger` (631), `test_14_maintenance_plans` (431), `test_15_gate_ordering` (387), `test_16_access_control` (467).
>
> ## Coverage
>
> **144 test functions**, collected clean by pytest. **Queue A (§1.8) = 46** — all 23 difficulty instances at exactly 2 tests each. **Queue B (§1.9) = 98** — 98 of the 99 non-stub corner instances at ≥1 test. All 3 `excluded_because:` stubs were left untranslated and their `difficulty_instance` cross-references all resolve.
>
> Requirement-specific infrastructure: `assertions.assert_instant_equals` parses both sides and compares the *instant* — every one of the ~90 timestamp assertions routes through it, so `…T00:00:00Z` vs `…T00:00:00.000Z` can never be a false failure. `fixtures.add_quote_line` and `fixtures.deliver_salt` re-read the parent before writing, so no chain ever spends a stale `expected_*_version`. `fixtures.invoices_of` / `coverage_of` / `visits_of_plan` / `child_water_tests` are the only paths to the four cascade-created children that no creating call returns. `make_technician_headers(technician_id)` / `make_customer_headers(account_id)` are threaded through every ownership-gated call; `officer-alpha`/`officer-beta`/`officer-bravo` are distinct so the SoD pair on a confirmatory result is constructible on purpose.
>
> ## Skipped instance (1)
>
> **`Corner/cross_cutting_complexity_layers/corner_occ_quote_line_add_rejects_a_version_the_client_already_spent`** — failed **unique derivability**. Its core assert (replaying the same `expected_quote_version` after a successful add is refused, `Quote.version == 3` after two adds) requires the quote's `version` to advance on a line *add*. PRD §3.6 explicitly states the version bump for *pricing* and for *removal*, but never for the add; and §2.8 states the rule's own purpose as stopping "an estimator appending to a line set a permit condition has already reshaped" — a permit condition **does** bump the quote version (§3.7), so the OCC serves its stated purpose without the add bumping anything. A faithful PRD-only reader can ship either behaviour. `ERR_STALE_QUOTE_VERSION` therefore has no test; every other chain that adds a second line re-reads the quote first, which is correct under both readings.
>
> ## Assertions dropped inside instances that were otherwise kept
>
> These are **design-index slips against the PRD**, not weakened tests. Each instance still has its own test(s); only the listed sub-assertion was omitted.
>
> 1. **`permit_conditions_four_hop_cascade_holds_a_scheduled_work_order`** — dropped `Quote.status == REVISION_REQUIRED` (hop 3) and `WorkOrder.fulfillment_status == HELD` (hop 4). The instance's own chain creates the work order *from the approved quote*, which per §3.9 moves the quote `APPROVED → CONSUMED`. §3.7 then says the quote "moves `APPROVED → REVISION_REQUIRED` — or stays where it is if it was not `APPROVED`", and holds work orders only "because the quote left `APPROVED`". From `CONSUMED`, neither fires. Hops 1–2 and the quote reprice/`approved_total_cents` latch are asserted.
> 2. **`corner_payload_gate_family_rejected`** — dropped the `ERR_INVALID_DATE_RANGE` probe. Its setup leaves the work order `IN_PROGRESS`, so a `/schedule` call trips G5 (`ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE`) before G8. The other four gate rows are asserted, and `ERR_INVALID_DATE_RANGE` on scheduling is covered from a `DRAFT` work order by `corner_validation_schedule_window_end_must_be_strictly_after_start`.
> 3. **`corner_calc_billable_minutes_increment_and_floor_on_completion`** — dropped `wo_a.actual_end_at == 2026-06-03T12:00:00.000Z`. The instance advances the clock to `2026-06-04T12:00:00Z` (to start wo_b) *before* the trigger completes wo_a, so `actual_end_at` is stamped at 06-04. `actual_start_at` (which selects the band, hence 13500) is asserted.
> 4. **`corner_calc_callback_window_right_closed_at_day_ninety_for_labor_only`** and **`corner_callback_adjudication_gates_rejected`** — dropped `WorkOrder.callback_attempt_count == 3` from both. PRD names an increment of `callback_attempt_count` **only** on the out-of-warranty mutate-then-reject path (§2.11 item 3, §3.12); a reader who increments only there gets 1 and 0 respectively. The single-rejected-claim case (`== 1`) *is* derivable and is asserted in `corner_mutate_then_reject_callback_out_of_warranty_writes_persist`.
>
> ## Near-miss register — unverified hypotheses, to be re-checked against the code downstream
>
> 1. **`claim_count` incrementing on a *successful* claim intake.** Relied on: §3.12 "an `APPROVE` decision … requires that the coverage has not already been claimed `CALLBACK_MAX_PER_COVERAGE` (2) times — a `claim_count` beyond that limit is refused with `ERR_CALLBACK_LIMIT_REACHED`", plus §3.9 "Each opens with `status` `ACTIVE` and `claim_count` 0". Alternative faithful reading: `claim_count` rises only on the out-of-warranty path (the only place PRD states an increment), which makes `ERR_CALLBACK_LIMIT_REACHED` unreachable. I kept it because unreachability is the stronger objection. Distance from the edge: **zero** — `corner_callback_adjudication_gates_rejected` asserts `claim_count == 3` and depends on the approve at exactly count 3 being refused. If refuted, that test and the `claim_count == 2 / == 1` asserts in `corner_calc_callback_window…` all fail together.
> 2. **Quote subtotals recomputed on a non-`APPROVED` quote.** §3.7: "the quote moves `APPROVED → REVISION_REQUIRED` — or stays where it is if it was not `APPROVED`; **and** its subtotals, tax and `total_cents` are recomputed over the surviving `ACTIVE` lines". I read the recompute clause as unconditional. Alternative: a reader binds the whole sentence to the `APPROVED` case and leaves a `CONSUMED` quote's money frozen. Distance: `test_the_mandated_alternate_reprices_the_quote_over_the_surviving_lines` asserts 33280/2413/68693 — under the alternative it would still read 30800/2233/66033, i.e. a clean divergence on three fields.
> 3. **`ERR_QUOTE_INVALID_STATE` as the answer for an expiry sweep run at exactly 30 days.** §3.6 states the sweep "must be **strictly greater** than `QUOTE_VALIDITY_DAYS`" but names no error; §4.11's expire entry declares only `ERR_QUOTE_NOT_FOUND` and `ERR_QUOTE_INVALID_STATE`, so the error catalogue pins it by elimination. Alternative: a reader treats an in-window sweep as a 200 no-op leaving the quote `SENT`. Distance: one second — `corner_quote_expire_after_validity_window` probes at exactly `sent_at + 30d` and again one second later.
> 4. **The confirmatory child `WaterTest` carries the parent's `well_profile_id`.** §3.3 names only `parent_test_id`, `panel_type` and `result_status` on the child. `well_profile_id` is a required WaterTest field with one sensible value, but PRD never says so. Distance: `test_the_confirmatory_child_row_is_reachable_only_through_the_parent_filter` asserts the well-filtered `result_status=CLEARED_NEGATIVE` list returns **2** rows; a reader who leaves the child's well null returns 1.
> 5. **`ERR_TECHNICIAN_TIER_INSUFFICIENT` returning HTTP 403.** Taken straight from the §5 catalogue, but it is the only 4xx in the whole catalogue whose code disagrees with its gate's neighbours (every other G6 regulatory refusal is 422). Distance: zero — two tests assert 403 via the registered status map. Low risk, but the outlier is worth a downstream look.
> 6. **Emergency work orders started before their scheduled window.** Several corner setups schedule for a later instant and then `/start` while the clock still reads an earlier one (e.g. `corner_emergency_money_gates_rejected` starts three jobs at 12:00 that are booked for 12:00, 15:00 and 18:00). PRD gates `/start` on `SCHEDULED` alone and says nothing about the clock reaching the window, so I transcribed the instances as written. If an implementer adds an unstated "not before `scheduled_start_at`" precondition, those setups fail as "Setup failed" rather than as assertion errors.
>
> ## Confirmations
>
> - Every emitted test carries **exactly one** `Design:` line; 0 untagged, 0 dual-tagged, 0 tags resolving to a non-existent instance, 0 tags pointing at a stub (machine-checked against both YAMLs).
> - All 318 quoted PRD spans of ≥8 words survive a whitespace-normalised literal match against `workspace/PRD.md` (machine-checked; 10 initial mismatches were corrected to match PRD byte-for-byte).
> - No `pytest.mark.skip`, `skipif`, `xfail` or `pytest.skip()` anywhere in the suite.
> - `ast.parse` is clean over all 26 generated files; `pytest --collect-only` collects 144 tests with no import or collection errors.
> - Nothing under `workspace/implementation/` was read, listed or created, and no other task directory was consulted.

Orchestrator note: the 8 reachability claims and the 25 resolutions above are **routed into Step 8 as explicit work items** — at 0943 this hand-off produced 6 of Step 8's 7 edits when the suite itself was silent. They are hypotheses; Step 8/9 re-read the code and may refute them.

## Step 7: Run tests and iterate — 2026-08-09T13:48:30.000Z

Sweep was run from the pre-staged `sweep.sh` (two waves of four, `pkill` reaping inside the script file) rather than inline — 5 co-tenant `claude` sessions were live on this 8-core host at Step 7 start, though none was mid-sweep.

**Orchestrator-verified final state:** all 8 `results.*.json` at `passed=144 total=144 failed=0`; route table still exactly **121** `(method, path)` pairs; **144** test functions; **0** occurrences of `pytest.mark.skip` / `xfail` / `pytest.skip(` anywhere in `test_suite/` or `test_helpers/`.

Verbatim subagent summary:

> Route table verified at exactly **121** `(method, path)` pairs. Done.
>
> **Iterations run: 2.** Final sweep — and a second confirmation sweep — were both clean: **all 8 rounds `144/144`** (16 consecutive green rounds total). The opening sweep was `130/144` in all 8 rounds — perfectly deterministic, 14 unique failures collapsing to 5 root causes.
>
> ### Tests deleted
> **None.** Every failing test passed STEP 1 (verbatim PRD coverage) and STEP 1b (unique derivability).
>
> ### Fixes applied to `test_suite/`
> - `test_07_permits.py`, `_mandated_alternate_world` — the work order was created with scope `PRESSURE_TANK` and no permit naming it, so `/schedule` correctly returned `ERR_PERMIT_REQUIRED_NOT_APPROVED`. PRD 3.9 satisfies the prerequisite only via "the scope needs no permit at all" or a permit whose **`work_order_id` is this work order**; that second route is permanently closed in this world, because `permit_1` must stay `APPROVED` for `PRESSURE_TANK` on that well to supply the asserted `permit_fee_cents` 6000, and PRD 3.7 refuses to file any other permit for the same well *and* the same scope. The work order now carries `REPAIR` (PRD 3.7: "`REPAIR` and `MAINTENANCE` do not" require a permit; PRD 3.9 lets a work order carry any of the six scopes independently of its quote's). Fixed 2 tests; no asserted value changed. The same file's `_permit_prerequisite_world` already used the create-work-order-then-permit pattern, which is what pinned the intended construction.
>
> ### Fixes applied to `test_helpers/`
> **None** — the helpers were not implicated.
>
> ### Fixes applied to `implementation/`
> - `core.py`, `Ctx.touch` / `Ctx.flush` — **the 7-test `test_13` cluster and the `test_01` failure.** The version bump lived in `flush()`, which ran *after* the handler had already built its response body, so every mutation response shipped the **pre-mutation `version`**. A client echoing that back into the next `expected_invoice_version` was told its own fresh read was stale. `touch` now bumps on first touch (the `touched` map keeps it to PRD 2.5's "exactly one per entity per successful request"); `flush` is retained as a no-op marker. Verified safe by scanning every touch-then-raise site: all are PRD 2.11 `persist=True` rungs, and no handler calls a touching helper and then raises non-persist.
> - `serialize.py`, `DATETIME_FIELDS` — `last_inspection_completed_at` was the **only** `_at`/`_date` field missing from the renderer set, so it was dumped as a raw `datetime` and Flask rendered it as an HTTP-date (`Mon, 01 Jun 2026 09:00:00 GMT`), violating PRD line 100. Machine-checked the whole `FIELDS` table for other omissions — none.
> - `core.py`, `parse_instant` / `_TS_RE` — the regex accepted a space date/time separator and an absent zone designator, so `2026-06-01 12:00` parsed instead of raising `ERR_INVALID_TIMESTAMP` (PRD 2.7). Now requires the literal `T` and a zone designator; reduced precision, comma decimal marks and numeric offsets still parse. Confirmed by scanning every timestamp literal in the suite that this is the *only* non-canonical form used, and it is used solely as a rejection probe.
> - `r_field.py`, `accept_recommendation` — checked potability before expiry. PRD line 138 states verbatim "Within a single gate, checks are evaluated in the order the sections below give them", and PRD 3.4 names `ERR_TREATMENT_RECOMMENDATION_EXPIRED` before `ERR_POTABILITY_PENDING_CONFIRMATION`. Order swapped. (The §4 endpoint error list is *not* a precedence order — it puts `ERR_ACTOR_SCOPE_VIOLATION`, a G4 error, second.)
>
> ### Route table
> Confirmed **121** `(method, path)` pairs, unchanged. No endpoint, response field, side effect or capability was added; no PRD-required check was stripped; no data is seeded at startup.
>
> ### Prior-step hand-offs touched
> - **Step 5 near-miss #2** (quote subtotals recomputed on a non-`APPROVED` quote — 33280/2413/68693 vs 30800/2233/66033): **CONFIRMED.** Once the setup was fixed, `test_the_mandated_alternate_reprices_the_quote_over_the_surviving_lines` passes on the unconditional-recompute reading; the impl reads §3.7's recompute clause the same way. The three-field divergence never materialised.
> - **Step 5 near-miss #6** (emergency work orders `/start`ed before their scheduled window): **REFUTED as a risk.** `_schedule_regulatory` and the start path carry no unstated "not before `scheduled_start_at`" precondition, and no setup failed that way. The one `ERR_PERMIT_REQUIRED_NOT_APPROVED` setup failure was the *fixture's* fault, not an unstated impl precondition — the impl's gate is a literal transcription of PRD 408 (scope table, `work_order_id` match, `EMERGENCY` exemption, nothing more).
> - Near-misses **#1, #3, #4, #5** and all 8 Step 6 reachability claims were untouched by any failure and remain unverified.
>
> ### Environmental failures
> **None.** The host was quiet throughout (0 foreign `prd-bench-local-run` processes, load 0.33–2.3 against 8 cores). No round exited 143/144, no results file was missing, and every round of every sweep produced identical pass/fail sets — the opening sweep's 14 failures were byte-identical across all 8 rounds, which is itself evidence against saturation, so no falsification re-run was needed.

## Step 8: Finalize PRD — 2026-08-09T14:09:45.000Z

Not skipped (Step 7 applied 4 `implementation/` fixes). The `<step_7_diff>` handed over was **three-part**: (A) the Step 7 fix list, (B) impl-gen's 25 self-reported generation-time resolutions + its 8 reachability claims, (C) test-gen's skipped instance, 4 dropped sub-assertions, and 4 still-unverified near-misses. Part B/C routing is the 0943 practice — at that task it produced 6 of Step 8's 7 edits when the suite was silent.

Verbatim subagent summary:

> Done. `PRD_FINALIZED.md` is written.
>
> ## Scale
> - **PRD.md 1273 lines / 171,313 bytes → PRD_FINALIZED.md 1277 lines / 182,442 bytes** (+4 lines = **+0.31 %** by line, **+6.5 %** by byte — the PRD is one paragraph per line, so byte delta is the real measure). **29 source lines touched.**
>
> ## Changes (section — kind — what — impl anchor)
>
> 1. **§2.5** — insert — the version bump is part of the mutation, so every mutating response renders the **post-mutation** `version`/`updated_at` on every entity kind; OCC echo-back works without a re-read; also true of the 2.11 rungs' persisted rows. Also **dropped "several catalog parts"** from the completion example. — `core.py:565-585` (`Ctx.touch`), `core.py:594-603` (`flush` now a marker)
> 2. **§2.6** — insert — pre-G8 gates that read body fields read them **non-fatally** (per-check skip so G8 can answer `ERR_INVALID_TIMESTAMP`/`ERR_INVALID_ENUM`); named the confirmatory window checks and the adjudicate state gate, and noted the same-officer check reads no body and always runs. — `r_field.py:217-240`, `r_wo.py:489-498`, `core.py:601-607`
> 3. **§2.6** — revise — **§3's narrative order is the governing intra-gate precedence**; it outranks §2.6's G9B category sketch, and **a §4 error list is a membership list, never a precedence order.** — `r_field.py:365-373`, `r_quote.py:88-95`
> 4. **§2.4** — revise — parse strictness: literal `T` and a zone designator are required (`2026-06-01 12:00` → `ERR_INVALID_TIMESTAMP`); reduced precision, comma decimal, numeric offset parse; one parser everywhere. — `core.py:163-200`
> 5. **§3.1 (well)** — revise — `new_drawdown_gallons` carries the 1.0–120.0 range, `ERR_VALIDATION` outside. — `r_register.py:200`
> 6. **§3.1 (shares)** — insert — terminate has **no state precondition**; re-terminating succeeds and bumps again. — `r_register.py:320-328`
> 7. **§3.1 (catalog)** — revise — `part_number` uniqueness is **not enforced**, no error. — `r_register.py:426-436`
> 8. **§3.1 (catalog)** — insert — required-when-applicable else `ERR_VALIDATION`; **not-applicable attributes are force-nulled** (never echoed), after the field's own range check still fires. — `r_register.py:409-425`
> 9. **§3.3 (lab)** — revise — an omitted `coliform_present` takes the negative branch. — `r_field.py:199-206`
> 10. **§3.3 (lab)** — revise — chemical always copies `hardness_gpg` **including null**; only `INVALID_HOLD_TIME` leaves the well untouched, so a no-exceedance chemical result still bumps the well. — `r_field.py:207-213`
> 11. **§3.3 (confirmatory)** — revise — full child-`WaterTest` field list (well, technician, sample/analyzed, coliform, `hold_time_valid` true, analytes null, both officer ids null). — `r_field.py:262-279`
> 12. **§3.4** — revise — supersede cascade also bumps **each superseded recommendation's** own `version`. — `r_register.py:260-268`
> 13. **§3.4 (accept)** — revise — expiry is evaluated **before** potability, with the combined-violation answer stated. — `r_field.py:365-373`
> 14. **§3.6** — revise — quote creation does **not** examine the inspection's state. — `r_quote.py:33-55`
> 15. **§3.6 (line add)** — insert — `quantity` 0 is accepted outright; a successful add **raises the quote's `version` by 1**. — `r_quote.py:90-108`
> 16. **§3.6 (expire)** — insert — sweep inside the open window (incl. exactly 30 days) → `ERR_QUOTE_INVALID_STATE`. — `r_quote.py:222-227`
> 17. **§3.7 (file)** — insert — `post_hoc` with a null `work_order_id` fails with `ERR_POST_HOC_PERMIT_WINDOW_EXPIRED`. — `r_quote.py:331-338`
> 18. **§3.9 (HELD→SCHEDULED)** — revise — the return path does **not** re-examine the parent quote. — `r_wo.py:144`
> 19. **§3.9 (posting)** — revise — check order rewritten to non-well-cause → authorization → discontinued → quantity → stock → preauth; quantity 0 noted. — `r_wo.py:218-247`
> 20. **§3.9 (hop 3)** — insert — when several `PART` coverages are minted, the **first in mint order** is recorded as `superseded_by_id`. — `cascade.py:178-212`
> 21. **§3.9 (versions)** — revise — bump set corrected: **no catalog part is touched at completion**; the **well bumps unconditionally**; ticket only when it moves to `RESOLVED`; remedy adds superseded coverage, claim and original work order; created rows open at 1. — `cascade.py:249-289`
> 22. **§3.9 (cancel)** — revise — cancel from `SCHEDULED` **leaves `scheduled_start_at`/`_end_at` stored**; only `HELD` clears them. — `r_wo.py:294-306`
> 23. **§3.10** — revise — `evaluate-compliance` refuses only on the lifecycle axis; an already-`OVERDUE` or not-yet-due `ACTIVE` plan returns 200 unchanged with **no version bump**. — `r_maint.py:106-112`
> 24. **§3.11 step 7** — insert — eligibility reads the **property's own `account_id`**, once, before the split. — `cascade.py:76-80`
> 25. **§3.11 lines** — insert — under a split **each invoice gets a full line set numbered from 1 carrying undivided amounts**. — `cascade.py:121-147`
> 26. **§3.12 (void)** — revise — `ERR_WARRANTY_ALREADY_SUPERSEDED` answers **both** grounds incl. a standing `APPROVED_WARRANTY` claim. — `r_wo.py:448-461`
> 27. **§3.12 (intake)** — insert — `claim_count` and `callback_attempt_count` rise on **every** intake, in warranty or not; only the rejected path sets `EXPIRED`. — `r_wo.py:370-375`
> 28. **§3.12 (approve)** — revise — `coverage_state` is **not** re-checked; `claim_count` limit is **strictly beyond 2**, first biting on the third claim. — `r_wo.py:516-521`
> 29. **§3.12 (remedy)** / **§4.11 (create quote)** — revise — cross-reference for the first-minted-coverage rule; endpoint blurb no longer says "completed inspection". — `cascade.py:209`, `r_quote.py:33`
>
> ## Pre-edit search log (subject / paths enumerated / wording adjustment)
> - **Version observability** — (a) when a bump becomes visible, all 19 versioned kinds. (b) Read every mutating handler in `r_register.py`, `r_field.py`, `r_quote.py`, `r_wo.py`, `r_maint.py`, `r_bill.py`, `r_emerg.py`, `cascade.py`; confirmed `ctx.touch` precedes `serialize.dump` everywhere, incl. `cascade.complete_work_order` touching the work order last (dumped by `r_wo.py:288`) and `core.Ctx.new` exempting created rows. (c) Scoped the claim to "rows it carries"; added the 2.11 clause because those responses carry no entity.
> - **Intra-gate ordering** — (a) which list governs. (b) Enumerated **every** handler with ≥2 refusals: share create, write-off, schedule G6+G9, confirmatory G6, work-order create, quote approve, quote-line add, permit file, permit approve, callback intake, adjudicate, payment, salt delivery, part create, remedy raise, dispatch, inspection start. (c) **Found the trap**: `post_parts` follows §4.14's list, not §3.9's prose. Rather than let a blanket "§3 governs" statement create a new mismatch, I rewrote §3.9's posting order to the impl order (change 19), so the global rule is true everywhere.
> - **Instant parsing / rendering** — (a) datetime acceptance and emission. (b) `core._TS_RE`/`parse_instant`/`iso`, `serialize.DATETIME_FIELDS`, every `F(..., "datetime")`. (c) Said "one parser serves every datetime body field" instead of enumerating fields.
> - **Category attributes** — (a) required-vs-null semantics. (b) `r_register.create_part` and `patch_part`, `serialize.FIELDS["PartCatalogItem"]`, `cascade` reads of `rated_drawdown_gallons`, `common.pump_yield_check` read of `rated_gpm`. (c) Added "discarding happens **after** the payload gate" because `rated_drawdown_gallons` keeps its 1.0–120.0 range for every category.
> - **Completion bump set** — (a) which rows bump at completion. (b) `cascade.complete_work_order` hops 1–8 line by line; `posted_entries`; `common.active_plans_of_well`. (c) Qualified the ticket ("when its dispatch axis moves to `RESOLVED`" — a ticket that never reached `DIAGNOSED` can found a work order) and added the remedy-only rows.
> - **Every other edit** got the same treatment; the notable rescopes were: the void-coverage sentence (dropped a tempting `coverage_state`-EXPIRED claim as out of scope), the supersede sentence (dropped the "only while still `ACTIVE`" clause as out of scope), and the loyalty sentence (bound to step 11 rather than to "shared wells" generally).
>
> ## Sibling sweeps
> - **Version observability → every versioned entity**: swept all 19; no per-entity pin needed (one code path).
> - **Stated bump sets → every cascade that states one**: §3.1 tank replacement ✓, §3.2 inspection ✓, §3.4 accept ✓, §3.6 pricing/removal ✓, §3.7 permit cascade ✓, §3.11 issue/pay/void ✓, §3.12 adjudicate ✓ — **one sibling needed its own pin**: §3.4's *create* cascade omitted the superseded recommendations' bumps (change 12).
> - **Instant rendering → every `_at`/`_date` field**: Step 7 machine-checked `FIELDS` vs `DATETIME_FIELDS`; PRD line 100 already pins rendering universally, so no PRD edit.
> - **Intra-gate order → every multi-check gate**: swept 17 gates; **one sibling needed its own pin** (`post_parts`, change 19).
> - **Superseded-coverage choice → both statements**: §3.9 hop 3 and §3.12 remedy paragraph, both updated.
>
> ## Deliberately NOT patched
> - **Part A #2** (`last_inspection_completed_at` HTTP-date) — pure impl bug; §2.4 already pins rendering for *every* instant in *every* body.
> - **Part C sub-assertion 2** (`ERR_INVALID_DATE_RANGE` pre-empted from `IN_PROGRESS`) and **sub-assertion 3** (`actual_end_at` at the advanced clock) — both already uniquely determined by §2.6's gate order and §3.9 hop 1.
> - **Part C near-miss 5** (`ERR_TECHNICIAN_TIER_INSUFFICIENT` = 403) — §5's catalogue already says 403; impl agrees.
> - **Part B/near-miss #2** (recompute on a non-`APPROVED` quote) — §3.7 hop 3 already states the recompute unconditionally.
> - **Reachability claims 2, 3, 8** — verified dead/unobservable; PRD's prose is vacuous there, no behavioral divergence.
>
> ## Refuted / confirmed by reading the code
> - **REFUTED nothing new** — Step 7 had already refuted near-miss #6 (no "not before `scheduled_start_at`" precondition on `/start`); I re-read `r_wo.start_work_order` and confirm the refutation.
> - **CONFIRMED reachability claim 1** (`SCHEDULED → HELD` is dead): `create_work_order` forces the quote to `CONSUMED`, `approve_quote` only accepts `SENT`, and `CONSUMED` is terminal, so `approve_permit`'s `left_approved` is never true for a quote that has work orders. `HELD` is written nowhere else. Change 18 pins the return path anyway, describing what the code does rather than adding an unenforced precondition.

## Step 9: Complete PRD — 2026-08-09T14:30:20.000Z

Always runs. Source was `PRD_FINALIZED.md`.

**Orchestrator-verified after the fact:** no file under `workspace/implementation/` was modified by Steps 8 or 9 (newest impl source mtime 13:37, i.e. before Step 7 exited at 13:48) — the documentation steps stayed documentation steps. Final state re-confirmed: all 8 rounds `144/144`, route table **121** `(method, path)` pairs.

Verbatim subagent summary:

> All edits landed cleanly. `PRD_COMPLETED.md` is written.
>
> **Source vs output:** `PRD_FINALIZED.md` 1277 lines / 182,442 chars → `PRD_COMPLETED.md` 1281 lines / 192,221 chars (**+4 lines, +9,779 chars**), across 26 edit hunks.
>
> **Counts:** 26 edits — **21 ambiguity-pins**, **5 mismatch-revisions**.
>
> ### Change list
>
> - §2.1 — insert — ambiguity — the `CustomerContact` ownership-chain list omitted the two endpoints that compare `X-User-ID` to an `Account.id` directly (account read, account-invoice list) — `r_register.py:68,92`
> - §2.3 — insert — ambiguity — empty-valued pagination param = omitted; whitespace/leading `+` tolerated — `core.py:491`
> - §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence (the logical clock stamps many rows identically) — `core.py:327`
> - §2.3 — insert — ambiguity — filter comparison is against the stringified stored value; booleans match `true`/`false` case-insensitively; null fields match the literal `null` — `core.py:522`
> - §2.6 (G9) — insert — ambiguity — several body FKs resolve in §4 request-list order; leftmost failure wins — `common.py:41` + every `create_*` handler
> - §2.6 — **revise** — **mismatch** — "Two places rely on [non-fatal pre-G8 body reads]" was false: **G7 is a third** — an absent/non-integer `expected_*_version` skips the OCC comparison and G8 answers `ERR_VALIDATION` — `core.py:697-702`
> - §2.7 — insert — ambiguity — the **five-pass internal order of G8** (presence/type → enum → timestamp → negative-quantity → value constraints), each pass complete before the next, fields in §4 declaration order; explicit `null` on an optional field == omission (default applies), on a required field == `ERR_VALIDATION`; non-JSON / non-object body == `ERR_VALIDATION`; absent body == `{}` — `core.py:412-484,608`
> - §3.3 — insert — ambiguity — every supplied analyte is stored on the test row in **every** branch (incl. `INVALID_HOLD_TIME`, and a `hardness_gpg` on a bacteriological panel) — `r_field.py:182-185`
> - §3.4 — insert — ambiguity — a cited test of the wrong panel type or wrong `result_status` is `ERR_NO_TREATMENT_INDICATED` (PRD stated the requirement but named no error); it runs after G9A resolution — `r_register.py:229-233`
> - §3.6 — insert — ambiguity — quote approval routes **all** yield-gate failure modes (low yield, absent `measured_yield_gpm`, `rated_gpm` < `MIN_PUMP_GPM`) to `ERR_QUOTE_LINE_YIELD_EXCEEDED`, never `ERR_INSPECTION_REQUIRED` — `r_quote.py:182-198`, `common.py:153`
> - §3.7 — **revise** — ambiguity — approval shape decided by the **pair** only; lone `condition_text` is discarded; exactly one of the pair is `ERR_VALIDATION`; part resolved before line; check order line-state → part-status → category — `r_quote.py:376-398`
> - §3.7 — insert — ambiguity — the minted alternate line's `markup_pct_applied`/`unit_price_cents`/`extended_price_cents` also stay null until re-pricing, though the quote total already values it — `r_quote.py:408-419`, `common.py:130-138`
> - §3.7 — insert — ambiguity — refile leaves `jurisdiction_tier` standing (only `filed_at` and `fee_cents` reset) — `r_quote.py:460-465`
> - §3.9 — **revise** — **mismatch** — work-order creation does **not** examine the ticket's dispatch axis; the at-most-one count includes cancelled work orders; three checks in stated order — `r_wo.py:57-65`
> - §3.9 hop 3 — insert — ambiguity — supersede only when stored status is still `ACTIVE`; a `PART` supersede with zero finalised entries leaves `superseded_by_id` null — `cascade.py:206-212`
> - §3.9 hop 4 — **revise** — **mismatch** — the PRD's causal "Because a coverage was superseded" is false: claim resolution is independent of hop 3 finding an `ACTIVE` coverage — `cascade.py:214-222`
> - §3.9 hop 5 — **revise** — **mismatch** — the narrative order was inverted: the well is re-banded **first**, visits and plan intervals follow; earliest `PRESSURE_TANK` part wins when several; well refreshed even with no `ACTIVE` plan — `cascade.py:249-274`
> - §3.10 — insert — ambiguity — `filter_next_due_date` / `salt_next_due_date` are never stored, always derived at read — `serialize.py:143-146`
> - §3.10 — insert — ambiguity — filter change ignores `filter_media` (a `NONE`-media plan still stamps the date) and a first change is unguarded — `r_maint.py:90-98`
> - §3.11 — insert — ambiguity — exact invoice-line `description` labels; `PERMIT_FEE` line only when non-zero, `DISPATCH_SURCHARGE`/`TRIP_FEE` always on emergency — `cascade.py:125-147`
> - §3.11 — insert — ambiguity — under a shared-well split only the **first** issue moves `PENDING_INVOICE → INVOICED`; issuing is not blocked by `credit_hold` — `r_bill.py:57-59`
> - §3.11 — insert — ambiguity — settle only from `INVOICED`; first invoice of a split to settle carries the axis — `r_bill.py:92-96`
> - §3.11 — insert — ambiguity — void moves the axis only from `INVOICED`, and only then does the work order's `version` rise — `r_bill.py:115-118`
> - §3.12 — insert — ambiguity — coverage void reads the **stored** `status`, not the derived `coverage_state` (an "EXPIRED" coverage is still voidable) — `r_wo.py:451`
> - §3.12 — insert — ambiguity — claim intake resolves the coverage before the consumed/window tests, and **never checks that the coverage belongs to the addressed work order** — `r_wo.py:349-357`
> - §3.12 — insert — ambiguity — `adjudicated_by_user_id` is stored on approve and reject too, overwriting an earlier value — `r_wo.py:531`
> - §4.7 — insert — ambiguity — a part PATCH supplying none of the three fields still 200s and still bumps `version`; explicit `null` = no change — `r_register.py:465-468`
> - §4.14 / §4.18 — **revise** — mismatch/ambiguity — header prose realigned ("diagnosed emergency ticket" → state not examined; permit-approve request-list wording)
>
> ### Yield by category
> - Derivation ladder (§3.9 cascade / §3.11 construction) walked hop-by-hop against code sequence: **7 edits**, including all 3 hard mismatches in the cascade.
> - Preconditions enforced but not numbered rungs (grep of every raise/refusal site): **5 edits** (§3.4 panel-type error, §3.7 pair/`ERR_VALIDATION`, §3.10 filter-media, §3.12 coverage-ownership gap, §3.6 yield failure modes).
> - PRD summary statements distrusted and re-checked: **2** (§2.6 "Two places", §3.9 hop 4 "Because a coverage was superseded").
> - Version-ledger / conservation claims re-verified arithmetically: **4** (the three billing-axis "only when it stands at X" guards + the split's version consequences). The §2.12 inventory and ledger identities themselves both verified correct — no change.
> - Response-field shape (serializer diffed against §3 field lists, all 21 entities): **0 discrepancies** — the emitted field set matches everywhere; 2 edits about *how* fields are produced (derived-at-read plan clocks, null pricing fields on the alternate line).
> - Defaults / rejected branches / 201-vs-200: **all 18 `201` endpoints and every default verified matching — 0 mismatches**; 3 edits on rejected-branch silence.
> - Filter/ordering/pagination on the list endpoints: **4 edits**.
>
> ### Notable findings
> - **Likely implementation bug, documented faithfully:** `raise_callback_claim` (`r_wo.py:349`) never checks that the cited `warranty_coverage_id` was minted by the work order in the path. A customer can claim against any work order they own citing an unrelated coverage, and the warranty window is then judged on that foreign coverage's dates. Documented in §3.12 as the adopted behaviour.
> - **PRD claims found outright false against the code (3):** (a) §2.6's "Two places rely on this" — G7 is a third non-fatal pre-G8 body reader; (b) §3.9 hop 4's "Because a coverage was superseded" — the claim resolves independently; (c) §3.9 hop 5's stated order (visits before the well re-band) is inverted relative to the code, which must re-band first for the interval recomputation to be correct. §4.14's "diagnosed emergency ticket" was a fourth, weaker false claim.
> - Milder faithful documentation: permit refile leaves a stale `jurisdiction_tier` on a `DRAFT` permit with `fee_cents` 0, which is arguably inconsistent but is what the code does.
> - All 11 §2.14 "deliberately open" tensions were re-verified against the code — every pinned computational behaviour there matches the implementation, so §2.14 needed no edit.

Orchestrator note: Step 9's count (26) is **well below the recent 66–84 band**, and the reason is visible in the split — Step 8 had already spent 29 edits, and it spent them on the *right* things because Parts B and C of its diff handed it impl-gen's 25 self-reported resolutions and test-gen's near-miss register. The two steps together came to 55 edits; what changed is *which* step paid for them. The counter-evidence that Step 9 was not merely coasting: it still found **3 outright-false PRD claims**, all of them in exactly the place the prompt aimed it — the cascade narrative walked hop-by-hop against code order, where a *summary* sentence ("Because a coverage was superseded…") asserted a causal mechanism the code does not implement.

---

# Final state

| | |
|---|---|
| Tests | **144 / 144**, all 8 rounds of the final sweep (16 consecutive green rounds counting Step 7's confirmation sweep) |
| Route table | **121** `(method, path)` pairs — equal to scaffold §1.5 and PRD §4, symmetric difference empty |
| Step 7 | 2 iterations · **0 deletions** · 1 `test_suite/` fix (2 tests) · 0 `test_helpers/` fixes · **4 `implementation/` fixes** |
| Step 8 | 29 edits (PRD.md 1273 → PRD_FINALIZED.md 1277 lines, +6.5 % by byte) |
| Step 9 | 26 edits — 21 ambiguity-pins, 5 mismatch-revisions (→ PRD_COMPLETED.md 1281 lines) |
| Scale | 21 entities · 16 state machines · 46 calculations · 74 validations · 93 errors · 7 roles · 68 ladder rungs · 8-hop cascade · 9-gate write order |
| Skips | **0** `pytest.mark.skip` / `xfail` / `pytest.skip(` anywhere in the suite |
| Flakiness | none observed — the opening sweep's 14 failures were byte-identical across all 8 rounds |

Orchestrator note: the sibling sweep earned its keep twice here, and the second time is the more instructive. Swept against **17 multi-check gates**, it found `post_parts` following §4.14's list rather than §3.9's prose — so the blanket "§3's order governs" sentence Step 8 was about to commit would have been **false at one site**, i.e. the NO-NEW-MISMATCH rule firing exactly as intended. The fix was to move the *PRD* (rewrite §3.9's posting order to the impl's) rather than to weaken the global rule.

Orchestrator note: the `Ctx.touch`/`Ctx.flush` bug is the **0920 shape recurring** — *the serializer projects the entity before the version bump lands*, so every mutation response ships a stale `version` and the client's own fresh read is then rejected as stale by OCC. Here it was structural rather than local (the bump lived in a post-handler `flush()`), which is why it took out a 7-test cluster at once. Step 8 must not treat this as a pure impl bug: PRD §2.5's "exactly one bump per entity per successful request" says *how many*, not *when it is observable*.
