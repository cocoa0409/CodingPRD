# Worklog — task_0949_home_staging_real_estate_prep

Scenario (verbatim): `949. Home-Staging & Real-Estate Prep Service: consultation & scope (occupied/vacant), inventory & furniture-rental pull, staging install & lease term, de-stage/pickup scheduling, agent/seller billing & package, damage/loss, photography linkage, extension`

Difficulty requested: **harder than Expert** (beyond-Expert band).

## Step 1: Create task directory — 2026-08-09T00:00:00.000Z

Created `tasks/task_0949_home_staging_real_estate_prep/workspace/`. Index 0949 = max existing (0948) + 1.

## Step 3: Copy shared files — 2026-08-09T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0949_home_staging_real_estate_prep/workspace/INSTRUCTION.md`. (Run ahead of Step 2 since it is bash-only and independent.)

## Step 2: Generate scaffold — 2026-08-09T00:00:00.000Z

All three artifacts are complete and clean.

## Files
- SCAFFOLD.yaml (§1.0–§1.7 + `global_constants`, `gate_precedence`, `concurrency_rules`, `conservation_invariants`)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
- SCAFFOLD_CORNER_DESIGN.yaml (§1.9)

## Exact counts
| Dimension | Count | Target |
|---|---|---|
| Entities | **22** | 19–22 |
| Endpoints | **125** | 100–125 |
| State machines | **18** (18 non-linear: 11 cyclic, 4 branching, 1 parallel, 1 compound; `Project` carries two axes) | 14–18, >=6 non-linear |
| Calculations | **45**, **10 dual-variant** | 35–50, >=8 dual |
| Validations | **73 rungs**, one numbered ladder, priorities 1..73 contiguous | 60–75 |
| Error codes | **89** | 65–90 |
| Roles | **8** (4 opaque, 4 entity-backed; segregation-of-duties) | 6–8 |
| Global constants | **81** declared with values | — |
| OCC rules | **3** (`pull-commit-stale-project`, `extension-request-stale-lease`, `damage-finalize-stale-pickup`) | >=2 |
| Conservation invariants | **4** (warehouse on-hand, deposit money, photo entitlement, billed lease cycles) | >=3 |
| Cascade depth | **7** (pickup-complete -> pull -> lines -> units+vendor order -> lease -> invoice -> deposit -> project/property) | >=6 |
| `gate_precedence` gates | **10** (G1...G10, total order, each mutating endpoint names its subsequence) | 7–10 |

## Design instances
- **§1.8: 31 instances** across all 9 rule_ids (4/4/4/3/4/4/3/2/3).
- **§1.9: 137 instances — 133 non-stub + 4 `excluded_because` stubs.**

| §1.9 section | instances (non-stub) |
|---|---|
| entities | 37 |
| state_machines | 22 |
| errors | 26 (22) |
| validations | 16 |
| rbac | 9 |
| cross_cutting_complexity_layers | 8 |
| calculations | 10 |
| endpoints | 6 |
| consistency_model | 3 |

Coverage: **error codes 89/89**, **validations 73/73 (100%)**, **calculations 45/45 (100%)**, **endpoints 106/125 (85%)**, state machines 17/17 entities, roles 8/8. All nine guide sections represented. 164 instance names, zero duplicates across both files.

## Verdicts
`yaml.safe_load` OK on all three files. Two YAML classes had to be repaired mechanically: bare `?` in flow sequences (`input: [x?, ...]` -> quoted) and nested `[` in flow mappings (`$.data[0].id`, `grounds: [errors[...]]` -> quoted).

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 125 | §1.1 entities declared: 22
  §1.8 instances scanned: 31 | §1.9 instances scanned: 133 | Calls scanned: 3636
```

**Constants: 81 declared, 0 undeclared.** A suffix/prefix sweep (`*_DAYS|_RATE|_FEE|_CAP|_PCT|_CYCLES|MIN_*|MAX_*|DEFAULT_*` ...) returned 7 hits, all false positives (6 error ids ending `_LIMIT`/`_WINDOW`, 1 gate name). No forbidden concurrency vocabulary anywhere.

## Structural device
Two structurally different pipelines share one ladder. **Pipeline O** (occupied): EDIT/DECLUTTER/REFRESH scope -> billable `Visit`s -> hourly labour -> service-window extension, **no Lease row exists at all**. **Pipeline V** (vacant): room package -> `InventoryPull` over owned stock + vendor rental -> `Install` -> `Lease` in 30-day cycles -> `Pickup` -> `DamageAssessment`. They fork at `Project.workflow_state` AUTHORIZED and rejoin at CLOSEOUT; every rung outside the two arms is shared.

## Free intelligence for later steps
Issues found and **fixed** while writing the design chains (each was a live reachability hole):

1. **`POST /projects/{id}/invoices` double-materialisation.** Cascade hop 5 already creates the DRAFT invoice on Pipeline V, so the PICKED_UP->CLOSEOUT trigger would have minted a second one. Pinned: on the vacant arm it *returns the existing row*; on the occupied arm it materialises.
2. **`ERR_SELLER_CONSENT_REQUIRED` was shadowed by `ERR_AUTHORIZATION_CAP_EXCEEDED`.** Both fired on the same predicate. Split by acting role x payer type: rung 39 = ListingAgent on a non-SELLER payer (no consent path exists); rung 41 = ListingAgent on a SELLER payer without consent.
3. **`ERR_BROKERAGE_CAP_EXCEEDED` was unreachable** — any over-hard-cap contract tripped rung 39 first. Now reachable only when a Seller/BrokerageAdmin (cap == hard cap) authorizes, which is the only honest way to isolate it.
4. **`ERR_INSUFFICIENT_INVENTORY` contradicted the state machine** (empty candidate set -> UNFILLED, never an error). Re-scoped to "the pass filled **zero** units", which is a real outright rejection.
5. **`ERR_DEPOSIT_BELOW_MINIMUM` was unreachable** — `deposit_requirement` bumped sub-minimum amounts *up* to the floor. Removed the bump; the amount is computed honestly and refused at collection.
6. **`ERR_BELOW_MIN_LEASE_TERM` was shadowed by `ERR_VENDOR_MIN_TERM_VIOLATION`** whenever a high-minimum vendor was present. Swapped rungs 43/44 so both are independently reachable from one fixture.
7. **`ERR_INVOICE_ALREADY_PAID` was shadowed by `ERR_INVOICE_INVALID_STATE`** (G6 precedes G10). Rung 31 now carries an explicit named exception routing the already-PAID pay case to rung 69.
8. **`ERR_FISCAL_HOLD` was unreachable**: every G10-gated endpoint on a fiscally held project tripped an earlier G5/G6 rung first. Added `G10_FISCAL` to `request-reshoot` and listed it in rung 71.
9. **`Extension.requested_cycles` range `1..6` made rung 46 unreachable** (the shape gate ate it). Widened to `0..12` so rungs 45 and 46 both fire.
10. **`Project.authorized_at` was referenced by `service_window_end_date` but never declared.** Added.

Remaining, deliberately left as **un-prejudged friction** for the PRD/impl steps:
- **`ERR_LISTING_TERMINATED` (rung 15) pre-empts `ERR_FISCAL_HOLD` (rung 71) on the terminate path.** Terminating a listing sets `fiscal_hold` true, but the same G5 freeze it installs means no G10-gated endpoint on that project can ever reach rung 71 via the terminate route. The escalate route is the only live one. Not a bug — a genuinely narrow reachability corridor worth a Step-7 look.
- **`Deposit.forfeited_amount` has two producers** (`POST /deposits/{id}/forfeit` and the `POST /invoices/{id}/void` cascade); the scaffold declares both and pins the same arithmetic, but does not say what happens if both fire.
- **`Consultation.estimated_hours` is writable twice** — at creation and again at `submit-scope`. `contract_value` reads the submit-scope value. The creation-time value is inert on the vacant arm.
- **Endpoints untouched by any design instance (19/125)** are almost entirely single-entity GETs plus `pulls/release`, `visits/no-access`, `deposits/forfeit`, `invoices/void` and `installs/complete`'s occupied-arm mirrors — those transitions *are* exercised through cascades, just never as a direct call. Worth topping up at test-gen time if breadth over the endpoint surface matters more than over the claim surface.

**Orchestrator verification:** yaml.safe_load OK x3; SCAFFOLD.yaml carries neither design key; section counts confirmed independently (22 ent / 18 SM / 45 calcs / 73 val / 125 ep / 89 err / 8 roles / 81 constants / 3 OCC / 4 invariants).

## Step 4: Generate PRD — 2026-08-09T00:00:00.000Z

PRD generated at `workspace/PRD.md`.

**Size:** 673 lines / ~19,400 words. Structure: §1 Introduction · §2 with 12 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 pagination, 2.4 identity/version, 2.5 logical clock, 2.6 path/shape/ranges, 2.7 the ten gates + full 73-rung ladder, 2.8 money/rounding/component order, 2.9 OCC, 2.10 the two pipelines, 2.11 conservation invariants, 2.12 declared-but-unenforced values) · §3 with 9 workflow subsections · §4 endpoint table · §5 error table. Ends at §5, no audit footer.

**Hard contracts (verified mechanically):**
- **Contract 1 — Field-name coverage:** 187 required identifiers (all `entities[].fields[].name` + all `input`/`request_body` keys + all `path_params` + all summary-output keys). 187 present, **0 missing. PASS.**
- **Contract 2 — Rule coverage:** all 45 calculations rendered with formula, constants, evaluation order, rounding order and both/all variants; all 18 state machines with every transition's from/to, preconditions and side effects; all 73 validations with condition + error id + HTTP status + `applies_to` scope; all 3 `concurrency_rules` (write endpoint, `expected_*_version` field, mismatch rejection, exact error id + 412); all 4 conservation invariants with compensating pairs; both arms of every fork given equal density (occupied vs vacant, every payer arm, `APPROVED_FULL` vs `APPROVED_PARTIAL`, early vs late vendor cancel, repair vs replace, `NO_ACCESS` vs `REFUSED`, upgrade vs downgrade). **PASS.**
- **Contract 3 — §3 path purity:** 990 backticked tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path. **PASS.**

**Coverage counts:** 81/81 constants present with literal values (audited one by one; e.g. `2026-05-01T00:00:00Z`, 45.00/75.00/1800.00 holdover, 0.0825/0.0625 tax, 12/36/72-month bands with 1.00/0.70/0.45/0.25 factors, 4500.00/15000.00 caps, 180/60 shoot minutes). 89/89 error codes stated with their raising condition in §2/§3 prose (0 appear only in the §5 table). 125/125 endpoints in the §4 table (4 columns). 73/73 ladder rungs stated by number with error, status and scope; the 10-gate total order is stated explicitly along with the three "why this order" notes (G7 between state and authority, G5 as an ancestor freeze, G10 last).

**Un-prejudged tensions carried forward (rendered faithfully, not adjudicated):**
1. `RentalOrder.monthly_rate_total` — the field description says `unit_count x tier monthly_rent_rate x rate_multiplier`, the calculation says `unit_count x VENDOR_UNIT_BASE_RATE (85.00) x rate_multiplier`. Both stated.
2. Rung 44 — the check reads "`effective_term_cycles` <= `initial_cycles` + 6"; the error catalogue reads "`initial_cycles` below `effective_term_cycles`". Both stated.
3. Rung 53 `ERR_INSUFFICIENT_INVENTORY` — the check is per-`OWNED`-line availability at commit-at-full-fill; the catalogue condition is "the allocation pass filled zero units". Both stated.
4. Pull commit side effects — the state machine says the project's `workflow_state` **stays** `PULL_OPEN`, the endpoint says it moves `RESTAGE_REQUIRED -> STAGED` when re-staging. Both stated.
5. Extension survival test has two definitions — the per-line rule on the adjudicate endpoint (OWNED, or VENDOR with `effective_term_cycles >= billed_cycles + requested_cycles`) versus the state-machine precondition ("committed to another project's install inside the extended window"). Neither subordinated.
6. Property machine on Pipeline O — project close is named as the trigger for both `STAGED -> DESTAGED` and `DESTAGED -> CLOSED`, so one call must walk two hops. Rendered as written.
7. Closeout opener answers **HTTP 201** on the vacant arm while explicitly creating no row (it returns the cascade-materialised invoice). Stated plainly.
8. Rung 46 (`extension_cycles` + granted <= 6) applies at *request* time, before `granted_cycles` exists, as well as at apply time. Stated with both scopes.
9. `photo_entitlement_conservation` includes a term (`remaining_included_sessions`) that is not a stored field; rendered as an accounting residual.
10. `MIN_PHOTO_LEAD_HOURS` (24) and `RESTAGE_AVAILABILITY_RECHECK_DAYS` (3) are declared constants that no rung, calculation or endpoint consults — given their own §2.12 with values, neither invented into a rule nor deleted.

## Step 5: Generate unit tests — 2026-08-09T00:00:00.000Z

Test infrastructure and suite are complete. Final report:

## Totals

**195 tests** across 16 files, collected cleanly by pytest.
- **Queue A (Difficulty): 62 tests** — all 31 instances have exactly 2 tests each (audit: 0 shortfalls).
- **Queue B (Corner): 133 tags over 132 distinct instances** — 132 of 133 non-stub instances covered; one instance has an extra second test.
- All 4 `excluded_because:` stubs verified to resolve to real §1.8 instance names; none translated.
- 390 PRD citations machine-verified verbatim against `PRD.md` (whitespace-normalised) — 0 mismatches. No `skip`/`skipif`/`xfail` anywhere.

## Instances SKIPPED (1)

- **`Corner/validations/lease_below_the_minimum_term_rejected`** — asserts `initial_cycles: 2` -> `ERR_BELOW_MIN_LEASE_TERM` (422) at rung 43. But §2.6 declares the range "`initial_cycles` on a lease from 3 through 24 inclusive", and rung 8 (G3) precedes rung 43 (G8), so a PRD-only implementer returns `ERR_INVALID_REQUEST` (400). Any value that could reach rung 43 fails the shape gate first, so the rung is **unreachable** as written. Notably §2.6 explicitly carves out `requested_cycles` 0 as surviving the shape gate but makes no such carve-out for `initial_cycles`.

## Sub-assertions dropped from kept instances

1. `package_upgrade_and_downgrade_are_not_price_symmetric` — dropped `Invoice line_summary.package accumulated == 4000.00`. No invoice row exists on a STAGED vacant project (it is materialised at hop 5 of pickup-complete), so the accumulator is unobservable. Kept: tier returns to SIGNATURE, `contract_value` back to 7690.00.
2. `split_payer_rounding_remainder_lands_on_the_seller_share` — dropped `line_summary.split_agent_share` / `split_seller_share`. §2.8 pins `line_summary` to twelve named components; neither share is among them, and §3.3 states the arithmetic without naming a response field (computed-field silence pattern). Kept: contract 4145.00, deposit 1036.25, subtotal 2825.00, tax 233.06, total_due 3058.06.
3. `writes_against_a_closed_project_return_project_closed` — dropped `Property.prep_state == CLOSED`. See near-miss #5.
4. `second_reshoot_request_exhausts_the_entitlement` — dropped `photo_sessions_consumed == 1` (the adapted flow consumes 2). See near-miss #1.

## Setups ADAPTED (assertion preserved, chain changed)

- **`second_reshoot_request_exhausts_the_entitlement`** — the design re-requests a reshoot against the *same* source shoot, but §3.8 moves that shoot to `RESHOOT_REQUESTED`, so rung 30 (G6) pre-empts rung 51 (G8) and the asserted error is unreachable. Adapted: two completed non-reshoot shoots; the credit is spent on the first, exhaustion asserted on the second.
- **`pull_line_room_label_outside_the_scope_rejected`** — the design adds the offending line to a `SUBMITTED` pull, where rung 21 pre-empts rung 52. Adapted to a `DRAFT` pull already carrying its 4-unit vendor line (`requested_unit_count == 4` preserved).
- **`duplicate_active_project_on_one_property_rejected`** — the design books a *second consultation* on a STAGED property, which §3.1 refuses ("refused unless the property is in `NEW`"), making the setup unbuildable. Adapted: a second `POST /projects` against the *same* `SCOPE_APPROVED` consultation — rung 38 passes, rung 65 fires.

## NEAR-MISS REGISTER — hypotheses to verify by reading the code

1. **Reshoot exhaustion vs. shoot state (gate order).** Read chosen: rung 30 pre-empts rung 51 when the source shoot is already `RESHOOT_REQUESTED`. Rejected: the design's implicit reading that rung 51 answers. If the implementation checks entitlement before shoot state, my adapted test still passes — but the *design's* original scenario would then also pass, so this adaptation is conservative, not falsifying.
2. **`ERR_INSUFFICIENT_INVENTORY` — two PRD renderings.** §2.7 rung 53 says "at least one AVAILABLE item ... for **every** OWNED line"; the same rung then records the catalogue's alternative, "an allocation pass that **filled zero units**". I picked *filled-zero*. Forcing argument: under the every-line reading, §3.4's verbatim "An empty candidate set leaves the line `UNFILLED` instead" would be unreachable for owned lines, and `PARTIAL`, `resubmit_count`, `MAX_PULL_RESUBMITS` and the 0.70 floor would all be dead. Distance from the edge: the 0.7000-commit and 0.6000-refuse fixtures both submit with 3–4 unfillable OWNED lines; if the every-line reading is implemented, **6 tests fail at setup** (`setup_vacant_pull_exactly_seventy_percent`, `setup_vacant_pull_partial_sixty_percent`, and their dependents). This is the single largest correlated risk in the suite.
3. **`ERR_BELOW_MIN_LEASE_TERM` unreachable** (skipped instance). Read chosen: §2.6's declared 3..24 range binds at rung 8. Rejected: rung 43 owns the sub-3 case. If the implementation does *not* range-check `initial_cycles` at G3, the rung becomes reachable and my skip is a coverage gap, not a PRD gap.
4. **Pickup window anchor after an escrow round trip.** `_window_cleared_and_reset` drives under-contract -> fall-out -> mark-term-complete at clock == `end_date` (2026-10-08T09:00Z). Read chosen: the anchor is `end_date` (clock is *not* strictly before it), giving [10-13, 10-20]. Rejected: clock-anchored because the lease "reached ENDING" once already. The two readings coincide here only because clock == end_date exactly — **distance from the edge: 0 seconds**. Three tests depend on it (window-end inclusive, +1s exclusive, far-outside).
5. **Property `prep_state` on occupied-arm project close.** §3.1 pins *both* `STAGED -> DESTAGED` and `DESTAGED -> CLOSED` to the close action, while also requiring the project to be in `DESTAGE_PENDING`/`VISITS_OPEN`/`STAGED` for the first hop — but at close the project is in `CLOSEOUT`. Two faithful readings (property ends `CLOSED` vs. stays `STAGED`). I dropped the assertion rather than pick.
6. **`extend-window` from `AUTHORIZED`.** Rung 19 governs `/extend-window` but §3.2 never names its legal origin states. I followed the design and extend immediately after authorization. If an implementer restricts it to `VISITS_OPEN`, the third-extension test fails at setup.
7. **Second `POST /projects` against an already-consumed consultation.** No PRD sentence forbids one consultation backing two projects; rung 38 only requires `SCOPE_APPROVED` (terminal). A reader who adds an un-stated one-project-per-consultation rule would return a different error than `ERR_DUPLICATE_ACTIVE_PROJECT`.
8. **`mark-term-complete` on a `RESTAGE_REQUIRED` project.** Rung 26 only checks the *lease* state (`ACTIVE` is legal). §3.5 says the lease reaching ENDING "moves the project `STAGED -> DESTAGE_PENDING`" — from `RESTAGE_REQUIRED` that hop is silent. My tests assert only the lease/window, never the project state, on that path.
9. **`repair-in` from `AVAILABLE` bumping version to 3.** §3.4 verbatim allows it ("An `AVAILABLE` unit may be sent to the bench directly") and §2.4 pins +1 per mutation; the arithmetic 1->2->3 is derived, not quoted.
10. **Pull-line ordering under `list_pull_lines`.** I look lines up by id rather than positionally everywhere except where the design pinned `data[0]` on a single-row filtered list.

## Kept only by "agreement by construction" — flag for downstream verification

- **`test_the_order_total_rounds_once_and_differs_from_the_per_line_sum`** asserts `lease.monthly_rent != order.monthly_rate_total`. Both concrete values (679.84 / 679.83) are also asserted separately, so the inequality is redundant *given* those — it is not independent evidence.
- **`test_a_vendor_line_is_valued_on_the_vendors_flat_schedule_instead`** likewise asserts owned-drv != vendor-drv on top of the two literal values.
- The `assert_*_conservation` helpers (deposit, warehouse, lease cycles) are algebraic identities over fields the same test already pins literally; they add value only if the implementation returns a field set my literals do not cover.

## Reset witnesses (would fail on cross-test state leakage)

- `test_the_inventory_listing_honours_limit_and_offset` — plain unfiltered `GET /staging/inventory-items` must report `total_count == 3` and return exactly 3 rows.
- Plus filtered zero-count witnesses: `test_inventory_item_with_undeclared_category_is_invalid_enum` (0 items), `test_project_creation_against_a_submitted_but_unapproved_scope_is_refused` (unfiltered `list_projects() == []`), `test_an_undeclared_role_name_is_also_unauthenticated` (0 pulls), `test_an_install_before_the_vendor_lead_time_is_refused` (0 leases), `test_the_double_booked_project_stays_at_pull_open_with_no_install` (0 installs).

## Files

```
test_helpers/__init__.py                                42
test_helpers/api_client.py                             443   (125 endpoint methods)
test_helpers/api_errors.py                             192   (89 error ids + status map)
test_helpers/assertions.py                             351   (assert_same_instant + 22 entity asserts + 4 invariants)
test_helpers/constants.py                              186
test_helpers/factories.py                              144
test_helpers/fixtures.py                              1130   (33 composite fixtures)
test_helpers/test_users.py                              72
test_helpers/types.py                                  304
test_suite/conftest.py                                  51
test_suite/test_01_entity_not_found.py                 453   (22 tests)
test_suite/test_02_registration_and_defaults.py        381   (15)
test_suite/test_03_consultation_and_scope.py           209   (8)
test_suite/test_04_contract_value_and_package_pricing  182   (8)
test_suite/test_05_authorization_and_deposit.py        295   (12)
test_suite/test_06_warehouse_and_pull.py               476   (18)
test_suite/test_07_vendor_orders.py                    150   (5)
test_suite/test_08_install_and_lease.py                327   (12)
test_suite/test_09_extensions_and_holdover.py          281   (9)
test_suite/test_10_pickup_and_damage.py                605   (19)
test_suite/test_11_photography.py                      364   (13)
test_suite/test_12_occupied_visits.py                  125   (4)
test_suite/test_13_invoicing_and_deposits.py           387   (14)
test_suite/test_14_listing_lifecycle_cascades.py       242   (10)
test_suite/test_15_rbac_and_party_scope.py             246   (11)
test_suite/test_16_gate_precedence_and_concurrency.py  218   (10)
                                                      7856 total
```

All timestamp assertions go through `assert_same_instant()` (semantic instant comparison, `.000Z` vs `Z` agnostic) — zero raw ISO string equality checks remain. Entity-backed roles always carry real row ids via `make_listing_agent_headers` / `make_seller_headers` / `make_brokerage_admin_headers` / `make_vendor_rep_headers`; the shared constants are used only on probes that never reach a party-scope rung. The implementation directory was not read.

## Step 6: Generate implementation — 2026-08-09T00:00:00.000Z

Implementation complete and verified. Final state:

## What was built

`workspace/implementation/` — Python + Flask, **4,536 lines** across 18 files:

| module | lines | role |
|---|---|---|
| `calc.py` | 507 | all 45 calculations (Decimal, half-up) |
| `routes_exec.py` | 527 | installs, visits, leases, extensions |
| `routes_destage.py` | 459 | pickups, damage assessments, photography |
| `routes_core.py` | 457 | clock, brokerages, clients, properties, listings, tiers, vendors, inventory |
| `routes_consult.py` | 438 | consultations, scope items, projects |
| `routes_pull.py` | 377 | pulls, pull lines, rental orders |
| `cascades.py` | 291 | listing lifecycle, install-complete, 7-hop closeout |
| `routes_billing.py` | 249 | closeout, invoices, deposits |
| `gates.py` | 245 | the 10 gates / 73 rungs as named helpers |
| `serializers.py` 191 · `store.py` 189 · `consts.py` 140 · `errors.py` 137 · `lookup.py` 132 · `app.py` 102 · `envelope.py` 84 · `start.sh` 10 · `requirements.txt` 1 |

## Completeness gate

**scaffold pairs 125 / url_map pairs 125 / MISSING 0 / EXTRA 0** — (METHOD, path) pairs, `<...>` and `{...}` both normalised to `{}` on each side before diffing.

## The four adjudications

**1. Timestamps (three cases).** One canonical renderer, `store.iso()` — ISO-8601 UTC, exactly three fractional digits, trailing `Z`. (a) Server-generated instants read the **logical clock** (never wall clock) and render canonically. (b) Caller-supplied instants are parsed to aware UTC and **re-rendered in the same canonical form**, so `2026-05-01T00:00:00Z` echoes as `2026-05-01T00:00:00.000Z`. (c) Derived instants are whole-day (or whole-minute) arithmetic on their anchor, preserving time-of-day, rendered identically. All 23 datetime field names are registered in `serializers.DATETIME_FIELDS`, and `_value()` carries a catch-all `isinstance(value, datetime)` branch so no field can escape to Flask's HTTP-date encoder. `meta.api_request_timestamp` is the one deliberate exception: host wall-clock, because §2.5 scopes the logical clock to *business decisions*.

**2. Enum routing (closed list).** Exactly these 13 body fields route an invalid value to `ERR_INVALID_ENUM` (422): `client_type`, `occupancy`, `tier_code`, vendor `status`, item `category`, scope `action`, `recommended_tier_code`, `payer_type`, pull-line `source`, pull-line `category`, `condition_at_pickup`, extension `decision` {APPROVE,DENY}, damage `decision` {UPHOLD,REVISE}. **No other field routes here.** Named exclusions: `termination_reason` is a free string (no enumeration is declared for it anywhere), and query-string filters are never enum-validated (rung 7 is scoped to POST/PUT/PATCH bodies) — an unknown filter value simply matches nothing.

**3. Version observability.** `store.touch()` bumps `version` + `updated_at` **at the point of mutation**; serialization happens at `return`, so every mutation response ships the post-write version and a client replaying it into `expected_*_version` is accepted. Granularity is **per row per declared transition**, not per request: a request touching N rows bumps N versions, and a row taking two declared transitions in one request bumps twice — the lease on `extensions/{id}/apply` takes 2 (ACTIVE->EXTENDED, then the system EXTENDED->ACTIVE return, exactly as §3.5 requires). Pull commit bumps the pull once and the project once (even when it also carries RESTAGE_REQUIRED->STAGED); damage finalize bumps the pickup once; extension request bumps the parent lease by exactly 1.

**4. Boot.** `start.sh` guards `pip install` on a cheap `import flask`, reads `$PORT` (default 10000), binds `0.0.0.0`, `exec`s in the foreground. `app.py` pre-binds with a **bounded retry loop** (60 x 50 ms, `SO_REUSEADDR`, no fixed pre-sleep) and hands the fd to `werkzeug.make_server(fd=...)` — no `app.run()`, no `sys.exit(1)` on EADDRINUSE. Measured **12/12 clean boots** under immediate kill->relaunch.

## Storage

`grep -nE "sqlite|shelve|open\(|json\.dump|pickle|/tmp|\.db|redis" *.py` -> only two **docstring** hits (`store.py:3`, `app.py:4`); zero code hits. `grep -nE "seed|preload|bootstrap|fixture"` -> same two docstrings only. State is `STORE = {name: {} for name in COLLECTIONS}`, empty at import, dies with the process.

## Live verification

Three smoke suites, **0 failures each**, on fresh boots: full vacant pipeline (contract 3960 -> deposit 1188 -> allocation -> OCC commit -> install -> lease dates -> extension -> damage -> 7-hop closeout -> invoice 5345/125/4282 -> close, warehouse conserved at 4); full occupied pipeline (labour 1085, package 2500 with two window extensions, 2-hour floor, interest tiering, reshoot credit return); and cascades (under-contract -> fall-out -> restage, holdover 125 days -> 7575.00 with three cap resets, PAY_AT_CLOSING defer -> terminate -> escalate -> fiscal hold -> pay -> MLS delivery, vendor cancel 25%/100% across the strict cutoff).

## Reachability / PRD-silence / PRD-contradiction audit

**These are hypotheses for downstream verification by reading the code, not established facts.**

1. **Rung 41 is all but pre-empted by rung 39.** Rung 39 authorizes whenever the payer's `consent_on_file` is true regardless of `client_type`; rung 41 fires only when the payer is *not* a SELLER. The single reachable path is a `PlatformAdmin` setting consent on a non-SELLER client (the seller-consent endpoint permits PlatformAdmin against any `client_id`) who is then the payer while a ListingAgent authorizes above cap.
2. **Rung 43 vs rung 8 on `initial_cycles`.** §2.6 declares 3–24 (a 400); rung 43 declares `<3` -> 422. I loosened the shape gate to 0–24 so rung 43 stays reachable, following the precedent §2.6 sets explicitly for `requested_cycles`. If a test expects 400 for `initial_cycles: 2`, this is wrong.
3. **Rung 53 has two incompatible readings.** The precondition reading ("an AVAILABLE item for *every* OWNED line") would make PARTIAL and the whole resubmit machinery unreachable. I implemented the error-catalogue reading via a non-mutating dry-run: fires only when the resulting `filled_unit_count` would be 0. Rung 55 is still evaluated after 53 to keep ladder order.
4. **Rung 68 precedes rung 69 literally**, so an already-PAID invoice paid with a *wrong* amount answers `ERR_OVERPAYMENT` (422); only an exact-amount duplicate reaches 409.
5. **Contradiction — "a successful payment refunds the deposit residue per the waterfall."** The Deposit machine names only `/deposits/{id}/refund` as the REFUNDED trigger and rung 73 gates it on `invoice PAID`; auto-refunding at payment would make the refund endpoint permanently dead. Resolved for the state machine: payment does not touch the deposit.
6. **Contradiction — occupied-arm property `STAGED -> DESTAGED`.** Its precondition is `workflow_state IN {DESTAGE_PENDING, VISITS_OPEN, STAGED}` but its trigger is project-close, when the project is `CLOSEOUT`. Taken literally an occupied property never reaches DESTAGED or CLOSED. I run both hops on close (each with its own version bump).
7. **`swap_credit` is computed but never booked** — no `line_summary` component carries it and no sentence routes it there.
8. **RentalOrder cancel from CONFIRMED *before* the cutoff has no declared arc** (early arm is DRAFT/PLACED, late arm is PLACED/CONFIRMED). Returns `ERR_ORDER_INVALID_STATE`, though `vendor_cancellation_fee` is written state-agnostically.
9. **Suspended-vendor placement has no dedicated code** -> `ERR_ORDER_INVALID_STATE`.
10. **"Consumed rental order" is undefined** (rungs 42/44). Defined as project orders in {PLACED, CONFIRMED}.
11. **Vendor-line allocation widened to {PLACED, CONFIRMED}.** The literal "a PLACED RentalOrder" would make confirming before submitting leave vendor lines permanently UNFILLED.
12. **Pull `release` precondition dropped** ("pickup COMPLETED or lease CANCELLED") — hop 1 of pickup-complete already releases the pull, so enforcing it leaves the endpoint dead in the ordinary flow. Only `state == COMMITTED` is enforced.
13. **Extension adjudication when *no* deployed line survives** is undeclared (PARTIAL requires "at least one free"). Routed to APPROVED_PARTIAL with `extended_line_count = 0`; zero deployed lines vacuously yields APPROVED_FULL.
14. **Uniqueness violations have no declared error** (`license_code`, `email`, `mls_number`, `tier_code`, `sku`, room_label-per-consultation, pull_line_id-per-pickup) -> `ERR_INVALID_REQUEST` 400.
15. **FK type constraints have no declared error** (owner must be SELLER, listing agent must be LISTING_AGENT) -> 400, not 404.
16. **`requires_rental: true` on an OCCUPIED_PREP consultation** -> 400; rung 20 scopes `ERR_PIPELINE_MISMATCH` to `action` only.
17. **Consultation booking preconditions have no code** -> `ERR_CONSULTATION_INVALID_STATE` (property not NEW / live consultation exists) and `ERR_INVALID_REQUEST` (`scheduled_at` before the clock).
18. **Illegal listing origins on under-contract/terminate.** Rung 33 names its code only for close and fall-out. I use TERMINATED/CLOSED_SOLD codes for the terminal origins and `ERR_LISTING_NOT_UNDER_CONTRACT` as the residual for "already UNDER_CONTRACT".
19. **Invoice issue/defer extra preconditions** (`payer_type`, `workflow_state == CLOSEOUT`, listing state) all route to `ERR_INVOICE_INVALID_STATE`; no dedicated codes exist.
20. **Rung 19 is a no-op on upgrade/downgrade/extend-window** — the Project workflow machine declares no such transitions, so only rung 14 constrains them.
21. **Rung 14 not applied to listing lifecycle endpoints** — a Listing is neither a Project nor a Project child, and applying it would make a listing un-terminable once any of its projects closed. Their G5 is served by rungs 15/16 against the listing itself.
22. **Arithmetic dead end:** a BrokerageAdmin paying a non-BROKERAGE project's invoice *always* gets `ERR_NOT_PROJECT_PARTY`, since `project.brokerage_id` is null there.
23. **`effective_authorization_cap` re-derivation on a brokerage cap change is unreachable** — no brokerage update endpoint exists. `calc.redderive_caps_for_brokerage` is written and never called.
24. **`MIN_PHOTO_LEAD_HOURS` and `RESTAGE_AVAILABILITY_RECHECK_DAYS` are deliberately unenforced** (PRD §2.12) — declared, never read by a rule.
25. **Pull counts are not recomputed at commit**, though dropping UNFILLED lines changes the `state != DROPPED` population; recomputing would push a partial commit's `fill_rate` to 1.0000 and erase rung 54's observable evidence.
26. **`interest_accrued` keeps growing after payment** — its declared triggers are "GET the invoice" and "POST pay", with no stop condition, so a PAID invoice read long past `due_date` reports rising interest and `total_due`.
27. **The waterfall re-reads raw `damage_total`/`holdover_charge` on every run** (the formula is `d = min(avail, Pickup.damage_total)` with `+=` accumulation), so a second run against a positive residue re-consumes against the same targets. Implemented literally.
28. **Deposit apply with `held_remaining == 0`** satisfies "consumes the entire held_remaining" and lands APPLIED, not PARTIALLY_APPLIED.
29. **Listing under-contract hop 1 restricted to VACANT_STAGING projects** — the cascade says "every Project in STAGED" but the Project transition carries `pipeline == VACANT_STAGING`; moving an occupied project there would strand it (its closeout path is STAGED -> CLOSEOUT).
30. **Install `no-access` from NO_ACCESS with `attempt_count < 2` has no declared arc** -> `ERR_INSTALL_INVALID_STATE`.
31. **`termination_reason` validated as a free string** — the Listing entity carries no such field and no enumeration is declared, so rung 7 does not reach it despite the scaffold note naming EXPIRED/WITHDRAWN.
32. **G4 is a no-op on `dispute` and `request-reshoot`** — both list G4_PARTY_SCOPE in their `gates:`, but no rung's `applies_to` covers them.
33. **Seller party check added to approve/reject-scope.** Rung 11's `applies_to` omits them, but §3.1 requires the approver to be the listing's agent or the property's owner; a non-owner Seller gets `ERR_NOT_PROPERTY_OWNER`.

**Orchestrator verification (independent):** `def test_` count = 195; zero skip/xfail; scaffold-vs-url_map (METHOD, normalised path) pair diff run independently -> 125/125, MISSING 0, EXTRA 0; persistence grep hits only two docstrings. `workspace/sweep.sh` pre-staged (2 waves of 4, SWEEP_DONE marker).

## Step 7: Run tests and iterate — 2026-08-09T00:00:00.000Z

**Result: clean 8-round sweep, 195/195 in every round.**

## Iterations & wall time
3 sweeps. Sweep 1 ~8 min (rounds 221 s), sweep 2 ~9 min (229–264 s), sweep 3 ~11 min (365 s wave 1 / 265 s wave 2 — a foreign pipeline, `task_0952_diaper_baby_essentials_subscription`, was co-tenanting the 8-core host). Failure trajectory: **79 -> 3 (+16 boot-flake) -> 0**.

## Tests deleted
**None.** Every failure resolved to a fixture bug, a test-model bug, or a real implementation bug. No test failed STEP 1a coverage or STEP 1b unique-derivability.

## Fixes to `test_helpers/`
- `test_helpers/fixtures.py` :: `new_listing_agent` — created LISTING_AGENT clients with **no `brokerage_id`**, which PRD §3.1 requires verbatim ("A `brokerage_id` is required when the client is a `LISTING_AGENT` or a `BROKERAGE_ADMIN` and is null when the client is a `SELLER`"). The PRD-faithful impl correctly answered `ERR_MISSING_FIELD`. **This single fixture bug caused 77 of the 79 failures.** Fix: the helper now stands up its own brokerage (per-email-derived unique `license_code`, `authorization_cap` 15000.00 so the agent's own 4500.00 personal cap still binds) when none is supplied. Sibling sweep: `new_brokerage_admin` already requires one; the only two direct `api.create_client` calls in `test_suite/` already supply one; no test asserts a brokerage/client list count, so the extra row is invisible.

## Fixes to `test_suite/`
- `test_10_pickup_and_damage.py` :: `test_the_fourth_pickup_reschedule_hits_the_attempt_limit` — encoded the **install/visit** increment model (count advances on reschedule). PRD §3.6 puts the pickup's increment on the **door event**: "`SCHEDULED -> NO_ACCESS` ... it increments `attempt_count`" / REFUSED "also increments `attempt_count`", while the reschedule sentence only gates on "strictly below 3". Rewrote the chain to no-access -> reschedule -> refuse -> reschedule -> no-access, so the third failed attempt closes re-booking; all three PRD-derived assertions (`ERR_PICKUP_ATTEMPT_LIMIT`, `attempt_count == 3`, `state == NO_ACCESS`) are preserved. Sibling sweep over the whole attempt-limit family: `test_08` (install) and `test_12` (visit) correctly use the reschedule-increment model per §3.4/§3.7 — the pickup was the sole divergence, and it was the test that was wrong.

## Fixes to `implementation/`
1. **`routes_consult.py` :: `authorize_project` — rungs 39/40/41 precedence.** Impl fired rung 39 on `headroom < 0 and not consent`, which swallowed both rung 40 and rung 41. That contradicts two emphatic PRD universals: rung 40 fires "regardless of who authorizes and **regardless of whether seller consent is on file**" (§3.2: "no matter who is acting and no matter what consent exists"), and §3.2 says a listing agent over their ceiling with no consent "is **separately** refused with `ERR_SELLER_CONSENT_REQUIRED`". Since every principal's cap is <= 15000.00, the old reading left rung 40 **entirely dead** on the authorize path. Rung 39 is now the residual: it fires only when neither the seller-consent path (payer is a `SELLER` -> rung 41) nor the platform ceiling (-> rung 40) owns the refusal. Sibling sweep of the cap family: `upgrade-package` already applies rung 40 unconditionally with no rung 39, matching the PRD's `applies_to`; unchanged.
2. **`routes_exec.py` :: `cancel_visit` / new `_settle_visits`.** §3.7 states `VISITS_OPEN -> STAGED` as a **condition over the visit set** ("once every visit on it is terminal ... and at least one is `COMPLETED`"), but the impl evaluated it only inside `complete_visit`. Cancelling the last open visit left the project stuck in `VISITS_OPEN` and closeout answered `ERR_PROJECT_INVALID_STATE`. Extracted to `_settle_visits(project)` and called from both arcs. Sibling sweep: `no-access` and `reschedule` produce non-terminal states, so they correctly do not settle. Also added the missing `rung14_project_closed` / `rung15_listing_terminated` guards to `cancel_visit` — rung 15 names "visit" explicitly and every sibling visit endpoint already carried them.
3. **`routes_consult.py` — deposit `held_remaining` at creation.** §2.10: "A deposit's `amount` **always** equals the sum of ... `held_remaining`. The identity is observable on **any single deposit read**", prefaced by "an implementation that lets one drift is wrong even when no single endpoint's rules were violated." The row was created with `held_remaining` 0 against a non-zero `amount`, breaking the invariant in `REQUIRED`. No PRD sentence assigns `held_remaining` a pre-collection value, so it now starts at the full amount and §3.3's "Collecting ... sets `held_remaining` to the full amount" re-asserts it. Sibling sweep of all four conservation invariants: warehouse and photography balance by construction; the **lease-cycle** one is explicitly broken at creation by the PRD's own sentence ("created ... with `billed_cycles` 0" while `initial_cycles` is N), so it is intentionally scoped from `ACTIVE` onward and was left alone. All `held_remaining` readers (waterfall, refund, forfeit) are state-gated, so none is reachable before `HELD`.
4. **`app.py` :: `_bind`** — widened the bounded retry from 60x50 ms (3 s) to 400x50 ms (20 s). 16 of the 19 sweep-2 union entries were `could not be restarted` boot flakes, concentrated in wave 2 while a foreign runner was co-tenanting; all 8 rounds allocated distinct ports (no registry collision), so the cause was a slow-dying predecessor, not a port steal. Zero boot flakes in sweep 3. No fixed pre-sleep was added — the kill->bind window is unchanged.

## Clean-sweep verification (actual numbers)
1. 8/8 `results.N.json` parseable, **195 individual test rows each**, `passed == total == 195`.
2. Identical test-name sets across all 8 rounds: **True** (195 unique names per round).
3. `def test_` in `test_suite/` = **195** == collected count.
4. `skip`/`xfail`/`skipif` in `test_suite/` + `test_helpers/`: **0 matches**.
5. `sqlite|json.dump|pickle|/tmp|shelve` in `$IMPL/*.py`: **2 hits, both docstrings** (`app.py:4`, `store.py:3`), zero code.
6. `Killed` **exactly once** in each of the 8 round logs, at line 19, on the first test — the expected per-test-server swap.

## Verdicts on the two predictions
- **Rung 53 / `ERR_INSUFFICIENT_INVENTORY` — CONFIRMED (agreement was real).** `routes_pull.py:181` implements the filled-zero reading via a non-mutating dry run: `if requested > 0 and (filled_now + filled_delta) == 0`. The 0.7000-commit and 0.6000-refuse fixtures — the 6-test correlated risk — passed in all 8 rounds of all 3 sweeps. The largest flagged risk never fired.
- **Rung 43 / `initial_cycles` — NEVER SURFACED, and the disagreement is real and still open.** `routes_exec.py:43` carries the loosened shape gate `("int", 0, 24)` so rung 43 answers 422 at line 63; test-gen skipped the instance, so nothing asserts either way. Reading the PRD myself, impl-gen's carve-out is **not** supported: §2.6 line 102 lists "`initial_cycles` on a lease from 3 through 24 inclusive" among the shape-gate ranges and grants an explicit survives-the-shape-check carve-out to `requested_cycles` **only**. A PRD-only implementer would return `ERR_INVALID_REQUEST` (400) for `initial_cycles: 2`, making rung 43 unreachable — test-gen's conclusion. I left the impl as-is (a reachable rung beats a dead one, and no test adjudicates), but this is a live PRD self-contradiction for the finalization steps.

## Fairness flags on passing tests
- `test_05::test_the_pay_at_closing_deposit_is_half_the_contract_value` — `assert_deposit_conservation` on a `REQUIRED` deposit is the assertion that drove impl fix 3. It is grounded in §2.10's "always"/"any single deposit read", but the PRD sets a **precedent against itself**: it explicitly creates a lease with `billed_cycles` 0 against a non-zero `initial_cycles`, breaking the parallel invariant at creation. §3.3's "Collecting the deposit ... **sets** `held_remaining` to the full amount" also reads oddly as a no-op now. Strongest candidate for a PRD sentence that should pin `held_remaining` at creation explicitly.
- `test_05::test_agent_over_own_cap_..._needs_seller_consent` + `test_contract_above_the_platform_ceiling_...` — fair only because rung 40's and §3.2's universals are emphatic; a reader applying §2.7's "first objecting rung supplies the error" mechanically to rung 39's literal text gets the other answer for both. The PRD should state rung 39's carve-out explicitly rather than leaving it to be inferred from rung 40/41 reachability.
- Carried forward from test-gen's own register (verified, not independently load-bearing): `test_the_order_total_rounds_once_and_differs_from_the_per_line_sum` and `test_a_vendor_line_is_valued_on_the_vendors_flat_schedule_instead` each assert an inequality that is redundant given the two literal values the same test already pins; the three `assert_*_conservation` helpers are algebraic identities over fields those tests pin literally.
- `test_12::test_a_cancelled_visit_contributes_nothing_to_the_labour_component` is **not** a fairness flag — §3.7's `VISITS_OPEN -> STAGED` sentence is verbatim and states a set condition, so routing it through cancel is derivable.

**Orchestrator verification (independent):** all 8 `results.N.json` parsed -> passed 195 / total 195 / 195 rows each; identical 195-name sets across all 8 rounds; 0 skip/xfail matches.

## Step 8: Finalize PRD — 2026-08-09T00:00:00.000Z

`PRD_FINALIZED.md` is written. Tables and §4/§5 intact; every edit traces to a listed diff item.

## Size
`PRD.md` 673 lines / 139,225 B -> `PRD_FINALIZED.md` 681 lines / 156,420 B (**+8 lines, +1.2 % lines; +12.4 % bytes** — most edits are in-paragraph). 43 diff hunks.

## Changes (section — kind — what — impl evidence)

**Part A**
- §2.7 rung 39 — revise — rung 39 restated as the **residual** cap refusal with its three carve-outs (payer `consent_on_file` true / payer is a `SELLER` -> rung 41 / `contract_value` > 15000 -> rung 40), plus the acting cap for a `BrokerageAdmin` = 15000.00 — `routes_consult.py:316-343`
- §3.2 — revise — same carve-out in the narrative authorization paragraph — `routes_consult.py:322-343`
- §3.7 — insert — `VISITS_OPEN -> STAGED` is a condition over the visit set re-evaluated on **every** terminal transition, so cancelling the last open visit settles the project; `NO_ACCESS`/re-booked visits are not terminal — `routes_exec.py:257-274, 296, 348`
- §3.3 — insert — deposit row is **created** with `held_remaining` = full `amount`; collection re-asserts it and changes nothing — `routes_consult.py:358-370`
- §2.11 — revise — deposit invariant holds from creation; **lease-cycle invariant scoped** to "from `ACTIVE`" (a `PENDING` lease has `billed_cycles` 0 vs non-zero `initial_cycles`) — `routes_exec.py:84-98`, `cascades.py:170`
- §3.6 — insert — pickup `attempt_count` advances **on the door event, not on the reschedule**, explicitly contrasted with install/visit; the *third* re-booking is the one refused — `routes_destage.py:105-151`. Swept §3.4 and §3.7: both already state their own (reschedule-increments) model unambiguously — no edit.
- `test_helpers` fixture bug: confirmed pure fixture bug; §3.1's `brokerage_id` sentence already matches `routes_core.py:72-82`. Only addition: a `brokerage_id` supplied on a `SELLER` is *ignored*, not refused.

**Part B (verified against code, then pinned)**
- §2.6 — revise — `initial_cycles` shape range **0–24** with the survives-the-shape-check carve-out, so rung 43 is reachable (`routes_exec.py:43,63`) — this resolves the live §2.6/rung-43 contradiction in favour of the code
- §2.6 — insert — uniqueness violations -> `ERR_INVALID_REQUEST` 400 (exhaustive 7-field list) and wrong-sub-type FKs -> 400 not 404, with the explicit non-generalisation for `payer_client_id` — `routes_core.py:16-19,136,177`
- §2.7 rung 7 — insert — **closed list of exactly 13 enum-routed body fields**, everything else free-string — all `enums(...)` callsites
- §2.7 rung 10/11 — revise — approve/reject-scope added to rung 11's applies-to; rung 10 on those two actions tests "agent of *at least one* listing on the property" — `routes_consult.py:165-171`
- §2.7 rung 14 — insert — listing lifecycle actions are not project children and are not gated — `routes_core.py:217-273`
- §2.7 rung 19 — revise — `/upgrade-package`, `/downgrade-package`, `/extend-window` removed from applies-to; no `workflow_state` is illegal for them — `routes_consult.py:374-440`
- §2.7 rung 33 — revise — full origin->code map for all four listing actions (`TERMINATED`/`CLOSED_SOLD`/residual) — `routes_core.py:207-215`
- §2.7 rung 44 — revise — **deleted** the opposite-side restatement; pinned `effective_term_cycles <= initial_cycles + 6` — `routes_exec.py:65-68`
- §2.7 rung 46 — revise — `requested_cycles` at request, `granted_cycles` at apply — `routes_exec.py:432, 513`
- §2.7 rung 53 — revise — **deleted** the per-line reading; pinned filled-zero non-mutating look-ahead, rung 55 still after it — `routes_pull.py:177-185`
- §2.4 — insert — one canonical instant rendering (3 digits + `Z`) for server/caller/derived instants; `meta.api_request_timestamp` is host wall-clock — `serializers.py:14-37`, `envelope.py:_request_ts`
- §2.3 — insert — filter values never enum-validated; `is_reshoot` boolean parsing — `store.where`, `envelope.qs_bool`
- §2.8 — insert — `package` component = current tier `base_price` + accumulated package adjustments — `calc.py:400`
- §3.1 — insert — brokerage cap re-derivation never runs (no brokerage update endpoint); consultation-booking refusals -> `ERR_CONSULTATION_INVALID_STATE`; `scheduled_at` before clock -> `ERR_INVALID_REQUEST`; `requires_rental` true on occupied -> `ERR_INVALID_REQUEST` — `routes_consult.py:37-43,110-112`
- §3.1 — revise — project close runs **both** property hops in order (occupied arm ends `CLOSED`), hop preconditions not re-checked at close — `routes_consult.py:455-457`
- §3.4 — revise — vendor `monthly_rate_total`: **deleted** the tier-rate reading, kept 85.00 base — `calc.py:228-229`
- §3.4 — insert — suspended-vendor placement -> `ERR_ORDER_INVALID_STATE`; `CONFIRMED`-before-cutoff cancel has no arc -> `ERR_ORDER_INVALID_STATE` — `routes_pull.py:328, 352-365`
- §3.4 — insert — **"consumed rental order" defined** as `PLACED` or `CONFIRMED` — `routes_exec.py:16-17`
- §3.4 — revise — vendor-line allocation widened to `PLACED`/`CONFIRMED` + spare-unit definition — `routes_pull.py:50-58, 22-28`
- §3.4 — revise — commit: project version bumps always; the two `workflow_state` statements cover disjoint cases (hedge removed); **counts are not recomputed at commit**; release enforces only the `COMMITTED` origin — `routes_pull.py:227-256`
- §3.4 — insert — install `no-access` from `NO_ACCESS` below the cap -> `ERR_INSTALL_INVALID_STATE` — `routes_exec.py:172-173`
- §3.5 — insert — extension outcome partition incl. zero-deployed -> `APPROVED_FULL` and zero-surviving -> `APPROVED_PARTIAL`; per-line survival rule made operative — `routes_exec.py:479-495`, `calc.py:240-247`
- §3.5 — insert — `swap_credit` is booked nowhere — `calc.line_summary` has no such component
- §3.8 — insert — `photo_sessions_consumed` is **derived on read** (non-reshoot shoots in `COMPLETED`/`DELIVERED`), so a reshoot request lowers it — `serializers.py:105`, `calc.py:350-352`
- §3.9 — revise — under-contract hop 1 restricted to `VACANT_STAGING` projects — `cascades.py:66`
- §3.9 — insert — issue/defer extra preconditions all -> `ERR_INVOICE_INVALID_STATE` — `routes_billing.py:63-90`
- §3.9 — revise — **deleted** "a successful payment refunds the deposit residue"; payment does not touch the deposit; rung 68 before 69 -> wrong-amount duplicate = `ERR_OVERPAYMENT` — `routes_billing.py:119-142`
- §3.9 — insert — invoice money re-derived on every read without bumping `version`; interest has no stop condition after `PAID` — `serializers.py:182`, `calc.py:467-501`
- §3.9 — insert — `termination_reason` is a free string, rung 7 never reaches it — `routes_core.py:264-266`

**Part C** — the four "two conflicting statements" sites (rung 44, rung 53, `monthly_rate_total`, pull-commit) each now carry one statement only. Near-miss 4 (pickup anchor) pinned in §3.5: the anchor is the clock **only** when, *at derivation time*, the lease is `ENDING` **and** the clock is strictly before `end_date` — both halves read live, so an escrow round trip landing exactly on `end_date` anchors on `end_date` (`calc.py:190-193`).

## Pre-edit search log (subject -> paths enumerated -> wording adjustment)
- **Rung 39 cluster** -> `routes_consult.authorize_project`, `_change_package` (upgrade's unconditional rung 40, no rung 39/41), `calc.effective_authorization_cap`, `gates.rung12` -> widened to name the `BrokerageAdmin` = 15000 cap and kept rung 40's applies-to list (authorize + upgrade) untouched.
- **Visit settlement** -> `_settle_visits`, `complete_visit`, `cancel_visit`, `no_access_visit`, `reschedule_visit`, `cascades.property_hop` -> added the "only while `VISITS_OPEN`" and "not terminal" clauses so no-access/reschedule paths are not mis-described.
- **Deposit conservation** -> `authorize_project` creation, `collect_deposit`, `calc.deposit_waterfall`, `run_waterfall`, `refund_deposit`, `forfeit_deposit`, `cascades.forfeit_deposit` -> identity verified at all six sites; sibling sweep to the lease-cycle invariant produced the scoping edit at §2.11.
- **Attempt counters** -> `_pickup_failure`, `reschedule_pickup`, `no_access_install`, `reschedule_install`, `no_access_visit`, `reschedule_visit` -> the blanket "counter advances at the door" rule is false for install/visit, so it is stated *as a contrast* and §3.4/§3.7 are left verbatim (fix at the outlier).
- **Pull counts** -> `add_line`, `submit_pull`, `commit_pull`, `cancel_pull`, `restage_availability_recheck`, `calc.recompute_pull` -> the "not-DROPPED" formula holds at 4 of 5 sites; commit is the outlier, so the exception is stated at commit rather than weakening §3.4's formula.
- **Invoice re-derivation** -> `serializers.invoice`, `calc.refresh_invoice` and its 9 callsites (issue/defer/escalate/pay/void/upgrade/extend-window/holdover/finalize/cancel-order) -> wording says "on every read *and* inside every operation that touches it" so no callsite is excluded; "never bumps `version`" verified against `store.touch` being separate.
- **Enum list** -> all 13 `enums(...)` callsites plus `types(...)` string fields -> added the explicit "no other field routes here" closure and the query-string exclusion.
- **Pickup window anchor** -> `calc.derive_pickup_window` and its 6 callers (`install_complete`, `begin_destage`, `listing_under_contract`, `apply_extension` x2, `listing_fall_out`'s explicit clear) -> wording made evaluation-time and strict so the `EXTENDED`/`ACTIVE` re-derivations (which anchor on `end_date`) stay correct.
- **Property hops** -> `cascades.property_hop` and all 8 call sites -> added "no-op unless already in the origin state" so the close-time double hop is described without contradicting the vacant arm.
- Every other edit had the same procedure applied; none required a further widening beyond those noted.

## Refutation list (claims checked and found wrong or vacuous)
1. **Part B 2 — impl-gen's rung-43 carve-out is *not* unsupported.** Step 7 judged it unsupported from §2.6's text, but the code is unambiguous (`("int", 0, 24)` + rung 43 at 422). Implementation is the alignment target, so §2.6 was changed, not the code. The contradiction was real; the resolution is the opposite of Step 7's reading.
2. **Part B 22 is not a PRD silence.** "A BrokerageAdmin paying a non-BROKERAGE project always gets `ERR_NOT_PROJECT_PARTY`" is a *derived consequence* of rung 12 comparing against a null `brokerage_id` (`gates.py:172-175`) — nothing to pin; no edit made.
3. **Part B 27 is already literally specified.** The waterfall does re-read raw `damage_total`/`holdover_charge` with `+=` accumulation (`calc.py:369-388`), but §3.3's existing prose says exactly that. Recorded, not edited.
4. **Part B 32 refuted.** "G4 is a no-op on `dispute` and `request-reshoot`" describes a scaffold artefact, not a PRD defect: §2.7's rungs 10–13 applies-to lists never mention those endpoints, and the code has no party check there. Nothing to fix.
5. **Part C 10 refuted as a silence.** `list_pull_lines` (and every list endpoint) uses `created_at` asc, `id` asc — exactly §2.3's stated ordering (`store.sort_default`). Internal processing order (`store.sort_created`) differs, but only for money sums that are order-invariant. No edit.
6. **Part C fairness flag on the closeout 201 refuted.** §3.9 and §4 already state 201 on both arms including the no-row vacant arm (`routes_billing.py:39`). Verbatim.
7. **Part C fairness flag on `photo_entitlement_conservation` refuted.** §2.11 already declares the `remaining_included_sessions` term "an accounting residual rather than a stored field". Verbatim.
8. **Part B 24 refuted as an edit target** — §2.12 already declares both unenforced values; `consts.py:106,112` agrees.

## Deliberately left for Step 9
- **`destage_eligible` "or the lease has reached its `end_date`, whichever happens first"** (§3.9): no code path sets the flag on the lease reaching `end_date` — a probable false PRD claim, but it is not the subject of any Step-7 diff item, so it was left untouched.
- **Rung 14/15 are not called on `POST /staging/pulls/{pull_id}/release`, `/cancel`, `inventory-items/*` and the deposit endpoints**, contradicting rung 14's "every mutating endpoint" universal. Out of scope here (only the release endpoint's *own* precondition was a diff item); flagged for Step 9.
- **`open_pull`'s "a pull is already live" refusal** uses `ERR_PROJECT_INVALID_STATE` with no PRD sentence naming a code — not in the diff, left alone.
- **One consultation backing two projects** (Part C 7): the code is permissive and the PRD is silent-permissive, which already agree; no sentence added.

## Step 9: Complete PRD — 2026-08-09T00:00:00.000Z

Done. `PRD_COMPLETED.md` is written; structure is intact (29 headings, 218 table rows, all 73 rung labels present, no new sections).

**Files** — `PRD_FINALIZED.md` 681 lines / 156,420 chars -> `PRD_COMPLETED.md` 684 lines / 182,776 chars (**+3 lines, +26,356 chars**), across **49 single-paragraph edits**. No new sections; every change is an in-paragraph insert or revision.

**Counts** — 35 ambiguity-pins, 14 mismatch-revisions (of which **5 are outright-false PRD claims**).

### Outright-FALSE PRD claims found (highest value)

1. **§3.9 — `destage_eligible` "or the lease has reached its `end_date`, whichever happens first"**. **CONFIRMED false.** `cascades.py:68-70` (`listing_under_contract`) and `cascades.py:52-54` (`begin_destage`) are the *only* two writes of `True`; `cascades.py:86` is the only write of `False`. Nothing anywhere compares the clock to `end_date` for this purpose. Revised to name the two explicit sources and state that a lease may run past `end_date` indefinitely with the flag still false.
2. **§3.5 — "`holdover_cap_period_start` advances ... and the period cap resets — which is the whole point of tracking the period start on the row."** **False mechanism.** `calc.holdover_charge(days)` (`calc.py:277-292`) takes only the day *count* and blocks it into runs of 30 **chargeable** days; `holdover_cap_period_start` is written at `routes_exec.py:394,401` and **never read by any calculation**. Because the grace days are subtracted before blocking, the block boundaries and the stored period boundaries do not coincide. Revised to "a record and not an input".
3. **§3.2 — "Travel is evaluated when the contract value is derived and again on each visit completion."** **False.** `routes_exec.py:276-297` (`complete_visit`) does not even refresh the invoice. Travel is re-read inside `calc.line_summary` (`calc.py:403`), i.e. on every invoice derivation. Revised.
4. **§3.5 — extension apply "incrementing the extension's `returned_line_count`."** **False.** The count is fixed at adjudication (`routes_exec.py:493`); `apply_extension` (`routes_exec.py:516-525`) never touches it, and skips any named line that has since left `DEPLOYED`. Revised.
5. **§2.7 rung 31 — "There is exactly one named exception on this rung."** **False.** `PAID` is carried past rung 31 to rung 69 on three endpoints, not one: `/pay` (`routes_billing.py:128`), `/void` (`:152-156`) and `/escalate` (`:105-108`). Revised to "one exception covering three endpoints".

### The three deferred items

| Item | Verdict | Evidence |
|---|---|---|
| `destage_eligible` on lease `end_date` | **CONFIRMED false** | see #1 above |
| Rungs 14/15 not called on `/pulls/*/release`, `/cancel`, `inventory-items/*`, deposits | **CONFIRMED, with one refutation** | Release/cancel/deposits confirmed. **Refuted for `inventory-items/*`**: those endpoints reach no project at all, so rung 14's own scope clause ("every mutating endpoint *that reaches a project*") was never violated there. Inventoried the true scope instead — **18** project-reaching mutating endpoints skip both rungs. |
| `open_pull`'s "a pull is already live" refusal has no PRD code | **CONFIRMED** | `routes_pull.py:80-82` raises `ERR_PROJECT_INVALID_STATE`. Pinned in rung 19. Note: with rung 19 already demanding `AUTHORIZED` and no arc returning to it, this branch is unreachable in practice — the code is pinned regardless. |

### Un-numbered-gate inventory (category 1)

| Check performed | Ladder position | Endpoints | Now stated |
|---|---|---|---|
| Conditional `brokerage_id` / `rental_order_id` required | G3, at rung 6, before rung 7 | `POST /clients`, `/projects`, `/pulls/{id}/lines` | yes §2.7 |
| `scheduled_at` before the clock -> `ERR_INVALID_REQUEST` | G3, after rung 9 | `POST /consultations` | yes §2.7 |
| Property `NEW` + no live consultation | between G4 and G6 | `POST /consultations` | yes §2.7 |
| `scoped_room_count` >= 1 | G6, after rung 18 | `/submit-scope` | yes §2.7, §3.1 |
| `requires_rental` false on occupied; duplicate `room_label` | G6, **after rung 20** | `/scope-items` | yes §2.6, §2.7 |
| Empty `DRAFT` pull -> `ERR_PULL_INVALID_STATE` | G6, after rung 21 | `/pulls/{id}/submit` | yes §2.7 |
| Vendor `SUSPENDED` -> `ERR_ORDER_INVALID_STATE` | G6, with rung 23 | `/rental-orders/{id}/place` | yes §2.7 |
| Duplicate `pull_line_id` per pickup | G6, **after rung 28** | `/pickups/{id}/damage-assessments` | yes §2.6, §2.7 |
| `DRAFT` assessment needs `IN_PROGRESS` pickup (rung 28's code) | G6, after rung 29 | `/damage-assessments/{id}/assess` | yes rung 29 |
| Lease state on apply (rung 26's code) | G6, **after** rung 27 | `/extensions/{id}/apply` | yes rung 26 |
| Pull `COMMITTED` before install *scheduling* | G6, after rung 20 | `POST /projects/{id}/installs` | yes rung 21 |
| Holdover eligibility x3 -> `ERR_LEASE_INVALID_STATE` | G6, at rung 26 | `/leases/{id}/accrue-holdover` | yes §2.7, §3.5 |
| Already-live pull -> `ERR_PROJECT_INVALID_STATE` | G6, after rung 20 | `POST /projects/{id}/pulls` | yes rung 19 |
| Vacant project at `STAGED` -> `ERR_PROJECT_INVALID_STATE` (not pipeline) | G6, at rung 19 | `POST /projects/{id}/invoices` | yes rung 19, §3.9 |
| `payment_state` + every-invoice-terminal -> `ERR_PROJECT_INVALID_STATE` | G6, at rung 19 | `POST /projects/{id}/close` | yes rung 19, §3.9 |
| `payer_type` fork + project/listing state -> `ERR_INVOICE_INVALID_STATE` | G6, at rung 31 | `/issue`, `/defer-to-closing` | yes (already in §3.9), cross-referenced |
| seller-consent identity vs `{client_id}` | G4, rung 11's code | `/clients/{id}/seller-consent` | yes rung 11 |
| Global uniqueness after rung 9 FKs | G3, after rung 9 | 5 creation endpoints | yes §2.6 |

Path resolution before body shape is uniform across all handlers, so a malformed date on an unknown parent yields 404 — already pinned by rung 5 < rung 6; no edit needed.

### All other changes

`§2.3` — insert — ambiguity — unknown query keys ignored; offset-beyond-total returns empty page (`envelope.py:67-70`) · `§2.3` — revise — ambiguity — the `id` tie-break is the *common* case since the logical clock never self-advances, and internal §3 orderings tie-break on write order instead (`store.py:168-174`) · `§2.4` — insert — ambiguity — version increments are per row per request, not per hop (lease bumps once at install-complete, twice on extension apply) (`cascades.py:162-199`, `routes_exec.py:530-539`) · `§2.4` — insert — ambiguity — free-form notes validated then withheld from every response (`serializers.py:70-73,92-96,167-170`) · `§2.6` — insert — ambiguity — the >=0/unbounded range family for all remaining numeric fields (`gates.py:103-143`) · `§2.6` — insert — ambiguity — uniqueness evaluated at its narrative position, not at rung 8 (`routes_consult.py:113-115`, `routes_destage.py:171-174`) · `rung 14/15` — revise — mismatch — true shared scope + the 18 exempt endpoints · `rung 19` — insert — ambiguity — legal origins per endpoint + four refusals sharing the code · `rung 21` — revise — mismatch — install scheduling added (`routes_exec.py:52-54`) · `rung 26/29/31/38/40/60/61/62/73` — insert/revise — legal-origin sets, scope corrections, projected-value test on upgrade (`routes_consult.py:387-390`), global crew count (`routes_exec.py:20-29`), reshoot skips rungs 48/50/62 (`routes_destage.py:430-459`) · `§3.1` — revise — mismatch — property hops test only the property's own origin state; consultation-cancel resets `prep_state` unconditionally (`routes_consult.py:211-215`) · `§3.2` — insert — 200-not-201 on authorize; tier change reads no `workflow_state`; unauthorized window extension leaves the date null (`routes_consult.py:420-440`) · `§3.3` — insert — void's forfeit is conditional on deposit state (`cascades.py:238-246`); waterfall doesn't check invoice ownership (`routes_billing.py:202-216`) · `§3.4` — insert x6 — orders live on both pipelines; null derived fields on `DRAFT`; 0.00 fee on unplaced cancel; `rental_order_id` required/unchecked-ownership; pull cancel re-runs counts to zero (`routes_pull.py:275`); install cancel leaves lines `ALLOCATED` (`routes_exec.py:162-171`); `crew_size` inert · `§3.6` — insert — pickup `lease_id` unchecked; de-stage start recorded once, without a version bump (`routes_destage.py:86-87`); cascade "because" is ordering not dependency; adjudicate is the one damage endpoint without rungs 14/15 and `revised_repair_cost` is optional · `§3.8` — revise — mismatch — completion re-tests rung 50, *not* "no pickup in `IN_PROGRESS` or `COMPLETED`" (`routes_destage.py:393-395`); `photo` component sums every shoot including cancelled/reshoot-requested (`calc.py:422-424`) · `§3.9` — insert x5 — under-contract hops 2/3 skipped while hop 1 lands; fall-out hops 2–4 unconditional, hop 4 owned-lines-only and `COMMITTED`-only (`cascades.py:102-120`); terminate's project axis conditional on an invoice actually escalating; close's 120-day sweep precedes the state move; escalate's sole origin; payment rounds both sides before comparing · `§4` — revise — the 201 rule tracks the response body, not side effects.

**Orchestrator verification (independent):** `find -newer results.8.json` over source files returns no `implementation/*.py` — Steps 8 and 9 touched documentation only. All 8 results files re-read: 195/195 each.

---

# PIPELINE COMPLETE — task_0949_home_staging_real_estate_prep

**195/195 x 8 rounds.** 0 test deletions · 1 `test_suite/` fix · 1 `test_helpers/` fix · 4 `implementation/` fixes · Step 8 = 43 hunks · Step 9 = 49 edits (5 outright-false PRD claims).
