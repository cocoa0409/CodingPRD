# Worklog — task_0934_smart_home_support_subscription

Scenario (verbatim): `934. Smart-Home Support Subscription: device inventory & onboarding, remote troubleshooting & ticket, install visit & scheduling, subscription tier & SLA, firmware/security update, add-on device sale, warranty/RMA routing, satisfaction`

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-08T17:15:00.000Z

Created `tasks/task_0934_smart_home_support_subscription/` and `workspace/`. Index 0934 = highest existing (0933) + 1.

## Step 2: Generate scaffold — 2026-08-08T18:25:00.000Z

All three artifacts are written and pass both YAML lint and the scaffold linter.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_0934_smart_home_support_subscription/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0934_smart_home_support_subscription/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0934_smart_home_support_subscription/SCAFFOLD_CORNER_DESIGN.yaml`

## Linter verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_0934_smart_home_support_subscription/SCAFFOLD.yaml
  Difficulty design:  tasks/task_0934_smart_home_support_subscription/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_0934_smart_home_support_subscription/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    77
  §1.1 entities declared:     17
  §1.8 instances scanned:     22
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  865

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Self-audit results

**(a) Incremental writes** — authored in 10 bounded Write/Edit calls; no oversized single write.

**(b) YAML lint** — all three files `yaml.safe_load` clean. Three offender classes hit and fixed: bare `field?` tokens inside flow `input:` sequences (PyYAML treats `?` before `,` as an indicator), nested `[` inside flow mappings (`captures: { r1_id: $.data[0].id }`, `grounds: [errors[X], …]`), and one `note:` accidentally inserted mid-`side_effects` list.

**(c) Undeclared-constant sweep** — scripted regex over every `ALL_CAPS_TOKEN`, subtracting enum values, state names and error ids. **39 declared constants, 0 undeclared.** All live in a top-level `domain_constants:` block and are echoed in the relevant `calculations[].constants`.

**(d) Reachability audit — 8 self-repairs**
1. `ERR_DISPATCH_NOT_REQUIRED` unreachable: rung 27 (`ERR_INVALID_STATE`) pre-empted it for every non-escalated ticket. Added an explicit exemption for `POST /visits` in rung 27.
2. `ERR_ROLLOUT_WINDOW_OVERLAP` unreachable: the launch precondition `firmware_status IN {CURRENT, ROLLED_BACK}` failed first. Relaxed to `NOT IN {BLOCKED, DEFERRED}` plus an explicit non-collision precondition; a device already `UPDATE_PENDING` now fires no firmware-axis transition, only a new rollout row.
3. `ERR_CAMPAIGN_HALTED` unreachable on report-result/defer (a halt blocks every PENDING rollout in the same request). Narrowed `applies_to` to `retry` only, with the reason stated inline.
4. **Arithmetic infeasibility**: the K=3 escalation could never fire — `Ticket.workflow` had no `REMOTE_DIAG → REMOTE_DIAG` self-loop, so a 2nd/3rd remote session was unopenable. Added the self-loop (guarded by "no session IN_PROGRESS").
5. `Device.firmware_status = UPDATING` had no producing transition → removed from the enum.
6. `Visit.status = EN_ROUTE` had no endpoint → removed (Visit is now a clean 3-way fork).
7. `Technician.status = INACTIVE` had no producer → dropped the whole field.
8. `Subscription ACTIVE → CANCEL_PENDING` carried a precondition (`status IN {ACTIVE, PAST_DUE}`) contradicting its own `from:` → tightened.

Verified programmatically afterward: every state-machine enum value is produced by some transition, every one of the 50 error codes is referenced by a design instance, 92/92 instance names unique across both design files, zero unbound `${var}`, zero forbidden race vocabulary.

**(e) Final counts**

| Metric | Value | vs target |
|---|---|---|
| Entities | 17 | 15–18 ✓ |
| Endpoints | 77 | 60–75 (+2, no near-duplicates; 30 are the mandated single-GET + FK-filtered-list pairs) |
| State machines | 14, **12 non-linear** | 10+ / ≥6 ✓ |
| Calculations | 23, **8 dual-variant** | 18–24 / 6+ ✓ |
| Error codes | 50 | 30–40 — 16 are mechanical `*_NOT_FOUND` (one per addressable entity); **34 are behavioural**, in band |
| Validation rungs | 51 | 30+ ✓ |
| OCC rules | 3 | 2–3 ✓ |
| Conservation invariants | 5 | 3–4 (+1) |
| Max cascade depth | **5** (RemoteSession → Ticket → Device → FirmwareRollout → FirmwareCampaign) | ≥5 ✓ |
| Declared constants | 39 (0 undeclared) | — |
| §1.8 instances | 22 across 9 rule_ids (3/3/3/3/2/2/2/2/2) | ≥18 ✓ |
| §1.9 instances | 70 (68 with recipes, 2 `excluded_because` stubs) | breadth ✓ |

Seam coverage: all 13 listed domain seams are exercised. Notables — the SLA clock is a three-way minute partition (counted/paused/uncovered) that is a conservation invariant; `Ticket` carries three independent axes and `Device` two; `gate_precedence` declares four ordered global write gates; the two temporal-overlap rules deliberately disagree on adjacency (half-open + 45-min buffer with strict `<` on Technician vs closed intervals where touching endpoints collide on Device); add-on pricing pins per-line-then-sum rounding (292, not 293) and keys the bundle discount to `subtotal_cents` alone even though `order_total_cents` crosses the next tier. Every formula-derived assertion literal was computed with a `Decimal ROUND_HALF_UP` script, not estimated.

## Step 3: Copy shared files — 2026-08-08T18:26:00.000Z

`cp ./INSTRUCTION.md tasks/task_0934_smart_home_support_subscription/workspace/INSTRUCTION.md`

## Step 4: Generate PRD — 2026-08-08T18:45:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_0934_smart_home_support_subscription/workspace/PRD.md`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

## Size
- **596 lines, 16,638 words.**
- Structure: §1 Introduction (3 paras) → §2 (11 subsections: RBAC, fixed response envelope, pagination, identity + version ledger, logical clock, money/rounding, OCC, the four ordered gates, the 51-rung ladder, conservation invariants, path resolution) → §3 (12 domain subsections) → §4 endpoint table → §5 error table.

## Confirmation counts
- **Endpoints documented: 77 / 77** (table rows counted mechanically).
- **Error codes documented: 50 / 50** in §5, and all 50 identifiers also appear in §2/§3 prose with a full-sentence trigger condition.
- **Constants documented: 39 / 39, each with its literal value** — verified by a scripted evidence check (e.g. `540`/`1020` UTC minute-of-day, weekend applicability true, 0.80 at-risk, 0.25/1.00 tier ratios, 0.05/0.15/0.30 credit pcts, 0.50 cap, 72h CSAT window, score ≤ 2, 0.10/0.05 CSAT pcts, 1440 min TTL, 3 attempts, 3 remote failures, 45-min buffer, 24h cutoff, 4500/9000 fees, 0.20 halt default, 2 retries, 14 defer days, 30-day cycle, 5-day proration floor, 20000/0.10 and 50000/0.15 bundle tiers, 12900 install fee, 5 max lines, 0.60 hold, 30 warranty-day floor, 14-day return window, 168h reopen, half-up, integer cents, clock default `2026-05-01T00:00:00Z`).
- **Validation rungs documented: 51 / 51**, as one explicitly priority-ordered list in §2.9 with "first failing rung wins, no later rung runs" stated, plus rung 21's exhaustive closed iff-list of enum-routed fields and rung 27's visit-booking exemption in favour of rung 40.
- Hard contracts: **Contract 1 PASS** (155 entity fields + 80 body-input identifiers + 18 query params, 0 missing; re-run a second time with the fixed §2.2 block stripped so envelope tokens could not mask domain fields — that pass caught `message` as a customer-reply field, which was then added). **Contract 2 PASS** (walked 3 OCC rules, 14 state machines / all transitions, 23 calculations incl. all 8 dual-variant pairs, 51 validations, all endpoint side-effect lists, entity defaults). **Contract 3 PASS** (363 backticked tokens in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path).

## Un-adjudicated friction points

**1. The vacated slot on a *late* reschedule.** The PRD states, as the endpoint's effect, that "the vacated slot is released to `OPEN`, the new slot is booked", and separately states that the state-machine rule under which a booked slot returns to `OPEN` on a reschedule carries the precondition that the logical clock is at or before `scheduled_start_at` minus 24 hours. *Reading A:* a reschedule inside the 24-hour cutoff still releases the old slot to `OPEN` (the endpoint effect is unconditional; the precondition merely describes the ordinary case). *Reading B:* inside the cutoff the release does not fire — the old slot goes to `BLOCKED`, or the reschedule is refused with `ERR_INVALID_STATE` — because the transition's precondition is unmet. No error code is nominated for this case anywhere in the scaffold.

**2. Which close-cycle effects apply on which hop.** The PRD gives the itemised per-hop effects (ACTIVE+SUCCEEDED, ACTIVE+FAILED, PAST_DUE+SUCCEEDED, PAST_DUE+FAILED, SUSPENDED+SUCCEEDED, CANCEL_PENDING+either) and separately gives the endpoint-level contract (roll `cycle_index` and the window forward 30 days, grant `included_install_credits`, recompute `install_credits_remaining`, reset `credits_issued_cents_this_cycle`, `overage_charges_cents_this_cycle`, `next_invoice_credit_cents` and `next_invoice_adjustment_cents` to 0, apply `pending_tier_plan_id`). *Reading A:* the per-hop list is exhaustive, so the `PAST_DUE → SUSPENDED` hop does **not** roll the cycle and grants nothing, the `SUSPENDED → ACTIVE` and `CANCEL_PENDING → CANCELLED` hops grant no install credits and reset no ledgers, and `next_invoice_credit_cents` / `next_invoice_adjustment_cents` are never reset on any hop (no hop itemises them). *Reading B:* the endpoint contract applies on every hop and the per-hop list only highlights the hop-specific extras, so all six hops roll the cycle, grant credits and zero all four ledgers.

**3. Whether add-on fulfilment mints an activation token.** The PRD states that claiming a device mints `activation_token` and sets `activation_expires_at` to the claim instant plus 1440 minutes, and states that fulfilment creates one `Device` per unit in `CLAIMED`, runs the warranty pin, records `fulfilled_device_ids` and recomputes the counters — without mentioning the token. *Reading A:* fulfilment mints `activation_token` and `activation_expires_at` exactly as a claim does, so the created units are activatable. *Reading B:* fulfilment mints neither (the field descriptions say the token is minted "at claim and re-minted at reclaim", and the fulfilment side-effect list omits it), so the created units carry a null `activation_token` until a support agent reclaims them.

## Self-consistency check
- **(a) Cascade summaries match hop lists — PASS.** The depth-5 escalation cascade is enumerated exactly once (§3.7, hops 1–5: session → ticket workflow/dispatch/`escalation_reason` → device `ACTIVE → SERVICE_HOLD` → rollouts `PENDING → BLOCKED_BY_SERVICE` plus firmware `BLOCKED` → campaign ring recount/completion); §1, §2.4 and §2.8 make no competing summary of it. The inverse release cascade (visit completion → `SERVICE_HOLD → ACTIVE` → `BLOCKED_BY_SERVICE → PENDING` → firmware `UPDATE_PENDING`) is stated identically in §3.8 and cross-referenced consistently from §3.4 and §3.9.
- **(b) Rung numbers cited in prose match the ladder — PASS.** Four citations exist: rung 27 cites rung 40 for dispatch-readiness, rung 40 cites rung 27 back, and §2.11 cites rungs 20 and 21 for filter-value routing. All four resolve correctly.
- **(c) No sentence asserts an enforcement no endpoint performs — PASS** with one deliberate carry-over: the scaffold declares `DeviceCatalogEntry.model_code` globally unique and "exactly one non-CANCELLED Subscription per household" but nominates no error code for either; the PRD renders both as properties of the data rather than as rejections, and names no error for them.
- **(d) Endpoint count == 77 — PASS** (mechanically counted in the §4 table; §5 carries exactly 50 rows).

One structural observation worth passing downstream (determinate, not a friction): because a `RING_ACTIVE` campaign auto-completes the moment its current ring holds no `PENDING` rollout while the failure rate is below the halt threshold, and `COMPLETED` is terminal, the `RING_ACTIVE → RING_ACTIVE` multi-ring launch is reachable only when the ring is emptied *and* the rate is at or above the threshold — in which case the campaign has halted instead. Both rules are stated faithfully and neither is softened.

## Step 5: Generate unit tests — 2026-08-08T19:12:00.000Z

Test infrastructure and suite are complete for `task_0934_smart_home_support_subscription`.

## Files written

**`test_helpers/`** — 2,450 lines across 9 files
`__init__.py` (43), `api_client.py` (357, one method per PRD endpoint, all under `/smart-home-support`), `api_errors.py` (116, all 50 error ids + status map registered), `assertions.py` (398), `constants.py` (164), `factories.py` (158), `fixtures.py` (592, five fixture tiers), `test_users.py` (71), `types.py` (551).

**`test_suite/`** — 4,434 lines across 13 files, **112 test functions** (`conftest.py` + `test_01_…` through `test_12_…`).

## Coverage

| Queue | Instances | Tests emitted | Skipped |
|---|---|---|---|
| A — Difficulty | 22 | **44** (exactly 2 per instance) | 0 |
| B — Corner (non-stub) | 68 | **68** (1 per instance) | 0 |
| B — `excluded_because` stubs | 2 | 0 (correct; both cross-references resolve to real difficulty instances) | — |

**No instance was skipped.** Every one passed the PRD-first two-condition filter. A machine check confirms: every test function carries **exactly one** `Design:` tag, every tag resolves to a real instance with a matching `rule_id`/`section`, all 216 quoted PRD citations survive a normalised-whitespace literal search of `PRD.md`, and there are **0** occurrences of `skip`/`skipif`/`xfail` anywhere.

## Friction points — all handled without picking a reading

- **Friction 1 (vacated slot on a LATE reschedule)** — **avoided.** The only reschedule instance (`reschedule_moves_the_visit_and_frees_the_vacated_slot`) runs with the clock at `2026-05-01` against a visit starting `2026-05-10T09:00Z`, i.e. 8 days before the `scheduled_start_at − 24h` precondition instant of `2026-05-09T09:00Z`. This is unambiguously an *early* reschedule, where both readings agree the vacated slot is released to `OPEN`. No test reschedules inside the cutoff.
- **Friction 2 (which close-cycle effects apply on which hop)** — **avoided.** The two close-cycle instances assert only the disputed-free surface: status hops (`ACTIVE→PAST_DUE`, `PAST_DUE→SUSPENDED`, `CANCEL_PENDING→CANCELLED`), the `Household.account_status`/`suspended_at` cascade, and `entitled_device_count`. No test asserts `cycle_index`, `cycle_start_at`/`cycle_end_at`, install-credit grants, or any of the four ledger resets on any hop — the entire disputed region.
- **Friction 3 (does add-on fulfilment mint an `activation_token`?)** — **avoided.** `addon_order_fulfillment_creates_one_claimed_device_per_unit` asserts order status, `fulfilled_device_ids` length, each device's `lifecycle_status`/`warranty_basis`/`warranty_expires_at`, the household counter and the invoice adjustment. It never reads `activation_token` or `activation_expires_at` on a fulfilment-created device.

## Determinate structural note (item 5)

No design instance requires a second ring launch on a still-running campaign — every launch in both indices is `ring_index: 1` from `DRAFT`. The `RING_ACTIVE → RING_ACTIVE` self-loop is therefore never exercised, so no reachability-driven skip was needed.

## PRD ↔ design-index disagreement (one, reported not silently resolved)

**`Corner/cross_cutting_layers/occ_addon_order_with_a_stale_subscription_version_is_rejected`** asserts `AddOnOrder.order1.order_total_cents == 24900` for a single-line order of one HUB at `msrp_cents` 24900. That contradicts PRD §3.10 Step 2: a subtotal of 24 900 is at least 20 000, so `bundle_discount_pct` is 0.10, `bundle_discount_cents` is `round_half_up(2490.0) == 2490`, and `discounted_subtotal_cents` is 22 410; with the single install credit covering the HUB (`install_charge_cents` 0) and no extras against `included_device_count` 4 (`proration_cents` 0), the PRD-derived total is **22 410, not 24 900**. I omitted that one assertion rather than pin either number, and kept the instance's actual distinguishing claim intact: the `ERR_STALE_VERSION`/412 rejection, `install_credits_applied == 1`, `install_charge_cents == 0`, `install_credits_consumed == 1` / `remaining == 0`, the install-credit conservation invariant, and exactly one `AddOnOrder` row surviving.

Two smaller, non-blocking notes where I stayed conservative rather than over-asserting: `household_creation_returns_declared_defaults_and_zero_counters` checks `suspended_at` via a helper that accepts both an explicit `null` and an omitted key (the PRD states the clearing rule but never the creation-time value); and `household_member_get_with_unknown_id_returns_not_found` rests on §2.1's `ERR_MEMBER_NOT_FOUND` sentence plus §3.1's "any single member row may be read by id" — the validation ladder has no rung for a member id in a *path*, only for the header identity, though the error catalogue leaves no alternative 404 for that endpoint.

**Orchestrator note on isolation:** Steps 5 and 6 were NOT launched in the same assistant message, so Step 5 completed before Step 6 started. Containment per the established protocol: `test_helpers/` and `test_suite/` were physically `mv`d out of the task tree to a scratchpad holding directory before Step 6 was spawned, and restored afterward. Step 6's prompt additionally forbade searching for or reading any test directory. Post-hoc check: `grep -rIl "test_suite\|test_helpers" workspace/implementation/` → empty.

## Step 6: Generate implementation — 2026-08-08T19:48:00.000Z

Everything is verified and the server boots clean through `start.sh`. Implementation complete.

## What was built

`{task_dir}/workspace/implementation/` — Python + Flask, 24 modules, **4,347 lines**:

| Module | Lines | | Module | Lines |
|---|---|---|---|---|
| `app.py` (entry, error handlers, G4 boot) | 120 | | `routes/tickets.py` | 423 |
| `ladder.py` (51 rungs, 4 gates, version ledger) | 397 | | `routes/dispatch.py` | 403 |
| `sla.py` (clock partition, tiers, credits) | 222 | | `routes/firmware.py` | 335 |
| `serializers.py` | 151 | | `routes/devices.py` | 326 |
| `timeutil.py` (the single renderer) | 141 | | `routes/addons.py` | 292 |
| `store.py` (in-memory, id minting, clock) | 142 | | `routes/billing.py` | 288 |
| `counters.py` | 125 | | `routes/rma.py` | 243 |
| `firmware_svc.py` | 120 | | `routes/sessions.py` | 139 |
| `envelope.py` 96 · `errors.py` 81 · `money.py` 77 · `warranty.py` 27 | | | `routes/households.py` 121 · `catalog.py` 51 · `misc.py` 27 | |

## Mandatory gates

**G1 — endpoint completeness.** declared **77** / url_map **77** / MISSING **0** / EXTRA **0** (programmatic set-diff after an in-process boot, path params normalised).

**G2 — timestamp rendering.** Adjudication, enforced by construction through `timeutil.render_instant`, the only function in the codebase that turns a datetime into an outbound string:
- **Server-minted** instants (`created_at`, `updated_at`, `api_request_timestamp`, `activated_at`, `activation_expires_at`, `first_response_at`, `resolved_at`, `closed_at`, `pause_started_at`, `survey_solicited_at`, `started_at`, `ended_at`, `cancelled_at`, `result_reported_at`, `shipped_at`, `returned_at`, `submitted_at`, `suspended_at`, `cycle_start_at`, `cycle_end_at`, `warranty_expires_at`, `return_deadline_at`, `window_closes_at`) → **`YYYY-MM-DDTHH:MM:SS.mmmZ`**, always exactly three fractional digits.
- **Derived** instants are server-minted too (`return_deadline_at = shipped_at + 14d`, `window_closes_at = solicited + 72h`, `cycle_end_at = start + 30d`, `activation_expires_at = clock + 1440m`) → same style, never echoing the caller's clock style.
- **Caller-supplied** instant strings are echoed **byte-verbatim**: slot `start_at`/`end_at`, campaign `ring_window_*`, rollout `window_*`, `deferred_until`, `purchase_date`, and the clock's `current_utc`. Copies stay verbatim (`Visit.scheduled_start_at` from the slot; rollout window from the campaign ring window).
- HTTP-verified on a live boot: a caller clock of `2026-06-01T12:00:00Z` (plain Z) produces `return_deadline_at = 2026-06-15T12:00:00.000Z`, `activation_expires_at = 2026-06-02T00:00:00.000Z`, `warranty_expires_at = 2026-07-31T00:00:00.000Z`, while `start_at` comes back exactly `2026-06-09T10:00:00Z`. A regex sweep over every instant field of 7 list endpoints found 0 deviations.

**G3 — enum error routing (closed iff-list).** A bad value routes to `ERR_INVALID_ENUM` (422) for **exactly these 14 fields and no others**: `tier`, `coverage_mode` (plan create); `member_role` (add member); `account_status`; `device_class` (catalog create); each element of `skills` (technician create); `severity` (ticket create); `outcome` (session complete); `kind` (campaign create); `result` (report-result); `payment_outcome` (close-cycle); and the three list filters `lifecycle_status`, `workflow_status`, slot `status`. **No other field routes here** — every other bad value is `ERR_INVALID_REQUEST` (400). Deliberate exclusions: all free-form id filters (`household_id`, `plan_id`, `pending_tier_plan_id`, `device_id`, `catalog_entry_id`, `transfer_target_household_id`, `opened_by_member_id`, `ticket_id`, `subscription_id`, `campaign_id`, `technician_id`, `slot_id`, `supersedes_rma_id`) never error, they simply match nothing; `limit`/`offset` are shape errors; computed enums (`warranty_basis`, `proration_mode`, `routing_target`, `fee_kind`, `credit_variant`, `breach_tier`, `reason`) are never inputs. Both sides HTTP-verified (9 enum → 422; 2 excluded filters → 200; 3 non-enum bad values → 400).

**G4 — EADDRINUSE-tolerant boot.** Own socket + `SO_REUSEADDR`, bounded retry (24 × 0.25 s = 6 s ceiling, then `sys.exit(1)`), served via `make_server(..., threaded=True, fd=sock.fileno())`. Verified: with a real listener squatting the port for 3 s, the server waited **2.88 s** and then bound; a tight kill ‑9/relaunch loop of **12 cycles gave 0 boot failures** and **0 PPID-1 orphans**.

**G5** — `start.sh` probes with `importlib.util.find_spec('flask')` and installs only if genuinely missing.
**G6** — plain Python dicts only; grep for `sqlite|pickle|json.dump|open(...w|/tmp/|seed_|preload` returns only a doc comment; no module-level `db.*` population; a fresh boot returns `total_count: 0` on all 13 list endpoints.
**G7** — Yes, monotonic UUID-shaped ids (48-bit counter in the high bits, valid UUID syntax). Verified: 25 ids all parse as UUIDs, ascend in creation order, and 20 members created at one frozen clock instant list back in exact creation order.

## The three friction adjudications

1. **Vacated slot on a LATE reschedule → Reading A** (released to `OPEN` unconditionally). The endpoint's own effect is stated without qualification, no error code is nominated anywhere for this case, and Reading B either invents an unstated `BLOCKED` effect or makes late rescheduling impossible. A is the only reading that keeps the endpoint reachable in all cases *and* preserves slot-capacity conservation on this path.
2. **Close-cycle effects → Reading B** (the endpoint-level contract applies on every hop; the per-hop list is hop-specific extras) — **with the one explicit per-hop negative honoured**. Reading A leaves the resets of `next_invoice_credit_cents` and `next_invoice_adjustment_cents` unreachable on *every* hop (no per-hop list mentions them at all) and the `install_credits_remaining` recomputation and `pending_tier_plan_id` application unreachable on 5 of 6 hops. But "No fresh install credits are granted on this hop" is determinate prose, not friction, so the grant fires only on the three hops landing in `ACTIVE` and is withheld on the two `FAILED` hops and the cancellation hop.
3. **Add-on fulfilment mints an `activation_token` → Reading A** (yes, instant + 1440 min). Reading B is self-defeating: reclaim requires `RECLAIMABLE`, and the only route from `CLAIMED` to `RECLAIMABLE` is a failed or expired activation attempt, which itself needs a token — so B would strand every fulfilled unit in `CLAIMED` forever and make `ACTIVE`, and with it every ticket/firmware/RMA behaviour declared for those devices, unreachable.

The determinate structural note is implemented as written and **not** softened: auto-complete fires whenever a `RING_ACTIVE` ring empties with the rate strictly below threshold, `COMPLETED` is terminal, and the `RING_ACTIVE → RING_ACTIVE` self-loop is left unreachable.

## PRD/SCAFFOLD divergences and adjudications worth flagging

- **Rung 7 vs gate 4.** A household whose only subscription is `CANCELLED` *has* a subscription; raising `ERR_SUBSCRIPTION_NOT_FOUND` at rung 7 would pre-empt gate 4 on every endpoint that needs the subscription and leave `ERR_SUBSCRIPTION_CANCELLED` unreachable there. Rung 7 now fires only when no subscription row exists at all. (Found and fixed by HTTP test.)
- **`accept-transfer` row scope.** §2.1 says a device's scope is `Device.household_id`; §3.4 says the acting member's `household_id` must equal `transfer_target_household_id`. Using §2.1 makes the endpoint unusable by its only legitimate caller. Implemented: scope compares `transfer_target_household_id` when set, falling back to `Device.household_id` when null — which keeps both `ERR_ROW_SCOPE_DENIED` (wrong household accepts) and `ERR_INVALID_STATE` (no transfer pending) reachable.
- **Technician row scope on rollouts.** §2.1 mentions "the slot behind ... the rollout whose result is being reported", but a rollout has no slot or `technician_id`; enforcing it would make `report-result` impossible for the role that owns it. Not enforced for technicians; Owner scope on a rollout goes through the device's household.
- **Customer-reply paused minutes.** §3.5's accumulator (`floor(now − pause_started_at)`) and §3.6's partition are both normative. The full partition is recomputed instead, because §2.10's conservation invariant is explicit; on whole-minute-aligned instants the two agree exactly.
- **Halt check runs after every result**, per §3.6/§3.9 prose ("After each result the campaign's counters are recomputed... halts when the rate ≥ threshold"), not only on `FAILURE` as the scaffold's state-machine trigger narrows it to.
- **`ERR_INVALID_STATE` on `SUSPENDED` + `FAILED` close-cycle** — no transition is declared for that hop.
- **Surveys and service credits have no not-found rung** in the 51-rung ladder; a missing id falls back to `ERR_INVALID_REQUEST` (400).

Test evidence: 5 HTTP suites (≈290 assertions) over live boots — happy paths, all 4 gates, ladder precedence, both coverage variants, breach tiers and the widened onsite base, the per-cycle cap and `ERR_CREDIT_CAP_REACHED`, all three CSAT variants, the depth-5 cascade, halt/resume/retry/defer, add-on pricing to the cent, RMA routing across all five branches, supersession, all five conservation invariants, and the version ledger — **0 failures**.

## Step 7: Run tests and iterate — 2026-08-08T20:05:00.000Z

Clean on the first sweep. No test deletions, no fixes of any kind were needed — the loop terminated at iteration 1, and I spent the remaining effort proving the zero is real rather than a false-clean.

## Summary

**Iterations run:** 1 (plus a second, independent confirmatory 8-round sweep = **16/16 rounds green**, 112/112 each).

**Tests deleted:** none. No test failed in any round, so no test entered the STEP 1 / STEP 2 protocol.

**Fixes applied to `test_helpers/`, `test_suite/`, `implementation/`:** none.

### Audit A — mechanical verification of the clean result
1. All 16 `results.N.json` parse; each holds **112 individual test rows** (not just an aggregate), `passed=112, failed=0, errors=0, skipped=0`, status set exactly `{passed}`.
2. Sorted test-name list **byte-identical across all 16 rounds** (sha256 `a6a00ee1236e`) — no round silently collected a smaller suite.
3. `def test_` = **112** == runner-collected **112** == `Design:` tags **112**; name sets equal.
4. Zero `skip`/`xfail`/`skipif`. The two grep hits are the English words "skipped"/"skips" inside docstrings.
5. Forbidden-pattern grep (`sqlite|json.dump|pickle|/tmp/|datetime.now|utcnow|time.time()`) → one hit, a doc comment in `store.py:5` disclaiming exactly those. Allowed.
6. Route diff, in-process boot, params normalised: declared **77** / live **77** / **0 missing / 0 extra**.
7. Every round log: `Killed` exactly once, `Traceback` 0, "could not be restarted" 0.
8. *Extra — positive proof of per-test isolation.* The `Killed`-once signature only shows a swap happened. Decisive evidence instead: PRD rung 29 makes `serial_number` globally unique across **every** `Device` row including `DECOMMISSIONED`, and `HBX000001` is claimed by tests in **6 different test files** plus the shared `setup_active_device` default. Without a real state reset the second such claim would be `ERR_SERIAL_ALREADY_CLAIMED`. All 112 pass in all 16 rounds, so state genuinely resets.

### Audit B — friction cross-check
The three friction surfaces are reachable through exactly **5 call sites in 4 tests** (3× `close_cycle`, 1× `fulfill_addon_order`, 1× `reschedule_visit`). I read all four.

- **Friction 1 (late-reschedule slot release) — CLEAN.** Clock at the reschedule is `2026-05-01T00:00:00Z` (`DEFAULT_CLOCK`; I verified `book()`, `setup_escalated_ticket` and `escalate_by_hardware_fault` contain no `set_clock`). Visit start `2026-05-10T09:00Z` → cutoff `2026-05-09T09:00Z`. Clock precedes it by **8d 9h**, an unambiguously *early* reschedule where readings A and B agree the vacated slot goes `OPEN`.
- **Friction 2 (which close-cycle effects on which hop) — CLEAN**, one item AGREEMENT-BY-CONSTRUCTION. The two tests assert only `status` hops, the `account_status`/`suspended_at` cascade, and `entitled_device_count`. The cascade is scoped to the `PAST_DUE→SUSPENDED` hop by *both* the per-hop bullet and the endpoint-level contract sentence, so it is hop-invariant under either reading. **Re-derivation of `entitled_device_count == 0`:** the household is created with `entitled_device_count` 0; the test's only device claim is *refused* with `ERR_SUBSCRIPTION_CANCELLED`; the counter is derived and "recomputed whenever the underlying device population changes" — the population never changed. It appears in neither the per-hop lists nor the contract, so 0 holds under A and B. **No test reads `cycle_index`, `cycle_start_at`/`cycle_end_at`, install-credit grants, or any of the four ledger resets after any hop** — the whole disputed region is untouched.
- **Friction 3 (fulfilment minting `activation_token`) — CLEAN.** The single fulfilment test asserts order status, `len(fulfilled_device_ids)`, the pricing triple, per-device `lifecycle_status`/`warranty_basis`/`warranty_expires_at`, `entitled_device_count` and `next_invoice_adjustment_cents`. It never reads `activation_token`/`activation_expires_at` and never activates a fulfilled device.

**Near-miss register — tests fair only by an incidental fixture value:**
1. **HIGH — `test_fulfilment_creates_one_claimed_device_per_ordered_unit`** (test_10:106). One call away: a single `activate(...)` on either fulfilled device makes it depend on Friction 3 (under reading B there is no token and the unit is stranded in `CLAIMED`). Fair only because the test stops at the `CLAIMED` serialisation.
2. **MEDIUM — `test_second_failed_close_cycle_suspends...`** (test_02:201). It moves the clock across two cycle boundaries but re-reads only `status`/`account_status`/`suspended_at`. One added `cycle_end_at` assertion lands squarely in Friction 2 — the `PAST_DUE→SUSPENDED` bullet is the one hop whose list omits the cycle-window roll, exactly where A and B diverge.
3. **MEDIUM — `test_cancelled_subscription_gate_blocks_a_device_claim`** (test_02:236). One assertion away: adding `next_invoice_adjustment_cents == 0` or `install_credits_remaining` after the `CANCELLED` hop would pin Friction 2.
4. **LOW-MEDIUM — `test_rescheduling_frees_the_vacated_slot...`** (test_08:269). Guarded by a literal date pair, not a structural fact; one `set_clock("2026-05-10T00:00:00Z")` crosses the cutoff. The 8-day margin means no incidental drift reaches it.
5. **LOW — the install-credit/proration tests** assert `install_credits_remaining`/`consumed`; safe only because no `close_cycle` runs in them (a re-grant would enter the disputed region).

**Known PRD↔design-index disagreement:** I re-derived it from PRD prose. Basket 1×HUB @24 900 → subtotal 24 900 ≥ 20 000 → 0.10 → discount `round_half_up(2490.0)`=2 490 → discounted **22 410**; 1 participating install unit covered by PLUS's 1 credit → `install_charge` 0; `included_device_count` 4 vs counter 1 → 0 extras → proration 0; total **22 410**, not the index's 24 900. Test-gen's omission is correct — the test asserts only the `ERR_STALE_VERSION`/412, the credit bookkeeping and the conservation invariant.

**Four spot-checks:**
- **(i) Response-field names:** 135 distinct `["..."]` accesses in non-docstring test code; **120 are API response fields and all 120 appear verbatim in PRD.md**. The 15 non-matches are local fixture-dict keys (`owner_headers`, `household_a`, `ticket_one`, …). **0 genuine misses.**
- **(ii) Numeric literals:** 45 distinct across 182 assertion occurrences. 14 verbatim PRD constants; 5 are test-supplied plan/catalog inputs echoed back (9999, 299, 399, 19000, 720); **26 derived, all hand-derived by me from PRD prose**. Pricing: 43900/4390/39510/**52410**; 50700/7605/43095/146/**43241** (11 days left of 30, per-line half-up); 798/**292** (146+146, vs 293 if summed once — the test asserts `!= 293`); 17800 (no tier); 19000→**31900** (tier pinned to subtotal, +12 900 install). Credits: cap `floor(1999×0.50)=999`, SEVERE `round_half_up(1999×0.30)=600`, second truncated to `min(600, 999−600)=399`, third → `ERR_CREDIT_CAP_REACHED`; onsite base widened `round_half_up((9999+299)×0.05)=515`, `500+515=1015`; CSAT `round_half_up(9999×0.15)=1500` + `round_half_up(9999×0.10)=1000` = 2500; goodwill `round_half_up(9999×0.05)=500`; `applied_to_cycle_index 2 = 1+1`. Upgrade `round_half_up(5000×15/30)=2500`. Holds `0.60×24900=14940`, `0.60×12900=7740`. Targets `168h×60=10080`. SLA partition `480+60+60=600` conserves exactly. **0 unexplained literals.**
- **(iii) Instant assertions:** **0** literal-string instant comparisons; 32 `assert_same_instant` calls, which parse both sides and compare `datetime` objects. **0 violations.**
- **(iv) List indices:** 8 indexed accesses; **8/8 on lists asserted `len(...) == 1`** immediately prior, so none depends on a PRD ordering rule. Where two rows coexist the suite uses `find_one(credits, reason=...)` rather than an index.

**Orchestrator's independent re-verification of the zero** (not taking the subagent's word): all 8 `results.N.json` re-parsed from disk → 112 individual rows each, `passed=112 failed=0 total=112`, status set exactly `{'passed'}`, sorted-name sha256 `a6a00ee1236e` identical in all 8; `def test_` 112 == `Design:` tags 112; `skip|xfail|skipif` count 0 across `test_suite/` and `test_helpers/`; `find ... -newer results.1.json` empty (no post-sweep edits).

## Step 8: Finalize PRD — SKIPPED — 2026-08-08T20:10:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes**. `PRD.md` already determined every behavior the implementation exhibits at every site the tests exercised, so there is no `<step_7_diff>` to patch. No `PRD_FINALIZED.md` is produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-08T20:35:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Exit summary

**Files:** `workspace/PRD.md` 595 lines / 118,749 chars → `workspace/PRD_COMPLETED.md` **595 lines / 140,960 chars** (+22,211 chars, **line count identical**, 55 diff hunks / 61 changed lines, all in-paragraph rewrites — no insertions or deletions of whole lines).
**Headings:** `diff <(grep '^#' PRD.md) <(grep '^#' PRD_COMPLETED.md)` is empty — all 31 `^#` headings byte-identical; the §4 table still carries 77 endpoint rows.
**Counts:** 33 ambiguity-pins, 22 mismatch-revisions.

### The three adjudicated frictions — all three verified in code and pinned
1. **Late reschedule** (`dispatch.py:264-266`): the vacated slot goes to `OPEN` unconditionally, no 24h precondition, no fee, ticket axes untouched. §3.8 revised (the PRD's "carries the precondition that the logical clock is at or before … minus 24 hours" was deleted as a live rule and replaced with the unconditional release).
2. **Close-cycle** (`billing.py:254-275`): endpoint-level contract fires on **every** hop including `CANCEL_PENDING → CANCELLED`; the one per-hop negative is honoured — fresh install credits only on the three hops landing in `ACTIVE`. §3.2 revised.
3. **Add-on fulfilment** (`addons.py:271-273`): mints `activation_token` + `activation_expires_at` = instant + 1440 min exactly as a claim. §3.10 revised.

### Reported adjudications — verified
All confirmed: rung 7 fires only on *no subscription row* (`ladder.py:376-389`); accept-transfer scope uses `transfer_target_household_id` with fallback (`devices.py:298`); technician scope **not** applied to rollouts (`firmware.py:217-221`); SLA paused partition recomputed in full (`sla.py:146`); halt tested after every result (`firmware.py:268`); `SUSPENDED`+`FAILED` → `ERR_INVALID_STATE` (`billing.py:249`); survey/credit single reads → `ERR_INVALID_REQUEST` 400 (`tickets.py:390,421`). **One correction:** the `RING_ACTIVE → RING_ACTIVE` self-loop is *not* strictly unreachable — a campaign that halts, is resumed, and then has its last `PENDING` rows removed by a deferral or service-hold cascade while the rate is still ≥ threshold stays `RING_ACTIVE` with an empty ring. §3.9 pins that narrow route rather than claiming unreachability.

### Changes (PRD_COMPLETED line — section)
19 §2.1 revise ambiguity header whitespace trimmed `ladder.py:72-80` · 27 §2.1 revise **mismatch** row scope: accept-transfer target, technician-reads-own-row, rollouts unscoped, lists unscoped `devices.py:298`,`dispatch.py:62`,`firmware.py:217` · 53 §2.2 insert ambiguity `api_request_timestamp` from the logical clock `envelope.py:32` · 82 §2.3 insert ambiguity non-integer pagination → 400 `envelope.py:67` · 84 §2.3 revise **mismatch** id tie-break, `has_more` formula, exact-match filters, no list scoping `store.py:134`,`envelope.py:50` · 88 §2.4 insert ambiguity server-rendered vs verbatim-echoed instants `timeutil.py:50` · 95 §2.4 revise **mismatch** member rows never mutated, `is_active` never cleared · 98-99 §2.4 revise ambiguity ticket bumps on no-op evaluate/reply, campaign bumps on rollout ops, Technician stays v1 `tickets.py:273`,`firmware.py:270`,`counters.py:60` · 107 §2.5 revise ambiguity `current_utc` echoed verbatim `misc.py:23` · 131-132 §2.8 revise **mismatch** gate-1 exemption set + source-household reading; gate 2 excludes launch-ring `firmware.py:84` · 145 rung 4 insert ambiguity single-member read `households.py:117` · 148 rung 7 revise **mismatch** cancelled ≠ absent; evaluation position `ladder.py:376` · 160 rung 19 revise **mismatch** single-row only · 161 rung 20 insert ambiguity full constraint list + unmatched route `ladder.py:208-304`,`app.py:54` · 162 rung 21 insert ambiguity fires only on present strings `ladder.py:261` · 165 rung 24 revise **mismatch** launch-ring exempt · 172 rung 31 insert **mismatch** first clause unreachable `devices.py:170` · 175 rung 34 revise **mismatch** decommission only from `ACTIVE` `devices.py:244` · 184 rung 43 insert ambiguity vacated slot still `BOOKED` `dispatch.py:255` · 208 §2.11 revise **mismatch** filter behaviour, 400 for unknown route/survey/credit `app.py:54`,`tickets.py:390` · 220 §3.1 revise **mismatch** member add is gated; `is_active` never cleared `households.py:89` · 222 §3.1 insert ambiguity CLOSED with no subscription `households.py:72` · 230 §3.2 revise ambiguity duplicate subscription → `ERR_INVALID_STATE`; defines "the household's subscription" `billing.py:83`,`ladder.py:348` · 236 §3.2 insert ambiguity change-tier from-states, required `allow_overage` `billing.py:155,185` · 238 §3.2 insert **mismatch** gate 1 blocks close-cycle on a suspended household; from-states `billing.py:215` · 247 §3.2 revise **mismatch** every-hop contract; no overage settled at close `billing.py:254` · 253 §3.3 insert ambiguity duplicate `model_code` → 400 `catalog.py:27` · 263 §3.3 revise ambiguity `firmware_version`/`transfer_target_household_id` null `devices.py:110` · 277 §3.4 revise **mismatch** target subscription required, gates read the source household, `is_overage` arithmetic `devices.py:300-325` · 283 §3.5 insert **mismatch** `device_id`/`opened_by_member_id` uncross-checked `tickets.py:41` · 291 §3.5 insert ambiguity workflow from-state not re-checked on dispatch-driven moves `dispatch.py:200,326,355,400` · 307 §3.6 revise **mismatch** projection's `sla_status` is the stored axis `tickets.py:126` · 309 §3.6 revise **mismatch** park/resume axis conditions; buckets recomputed not accumulated `tickets.py:183-209` · 325 §3.6 revise ambiguity no-op evaluation still writes+bumps; cap refusal writes nothing `tickets.py:257` · 333 §3.7 insert ambiguity session-open from-states, 201, ticket side effect `sessions.py:29` · 337 §3.7 insert ambiguity `HARDWARE_FAULT` leaves the counter `sessions.py:123` · 343-345 §3.7 revise ambiguity cascade hop 3/4/5 skip conditions `sessions.py:131`,`firmware_svc.py:17` · 347 §3.7 insert ambiguity completion returns the session `sessions.py:139` · 351 §3.8 insert **mismatch** `skills` consulted by nothing · 353 §3.8 revise ambiguity slot instants unvalidated for minute precision; technician self-scope `dispatch.py:62,72` · 361 §3.8 revise **mismatch** reschedule release unconditional (friction 1) `dispatch.py:264` · 367 §3.8 revise ambiguity `completion_notes`; conditional release cascade `dispatch.py:339`,`firmware_svc.py:44` · 373 §3.9 revise ambiguity any `ring_index` from DRAFT; narrow multi-ring route `firmware.py:96` · 377 §3.9 revise ambiguity every listed device bumped; verbatim window; ungated `firmware.py:147` · 381 §3.9 insert ambiguity halt tested after every result `firmware.py:268` · 383 §3.9 revise **mismatch** resume preserves the rate → next result re-halts `firmware.py:175` · 387 §3.9 revise ambiguity defer has no floor; from-state first `firmware.py:285` · 389 §3.9 revise ambiguity retry re-tests neither halt nor completion `firmware.py:326` · 393 §3.10 insert **mismatch** household/subscription uncross-checked, no status precondition `addons.py:64` · 411 §3.10 revise **mismatch** serial count, token minting, `is_overage`, no subscription bump `addons.py:216-291` · 415 §3.11 insert **mismatch** no device from-state, ticket uncross-checked, subscription check after the gates `rma.py:27` · 417 §3.11 insert **mismatch** remaining warranty days not persisted `rma.py:47` · 427 §3.11 revise ambiguity all priors superseded, most recent recorded `rma.py:76` · 431 §3.11 revise ambiguity ship's device leg conditional `rma.py:162` · 433 §3.11 revise ambiguity receipt past the deadline → `ERR_INVALID_STATE` `rma.py:190` · 435 §3.11 revise ambiguity charge only when `HELD`; other statuses → `ERR_INVALID_STATE` `rma.py:216` · 450 §3.12 insert ambiguity survey always created 201, no ticket bump `tickets.py:352`.

### Per-question yield
Q1 field-nobody-reads **5** (`skills`; `monthly_delta_cents`/`is_overage` next-cycle fee never charged; RMA remaining-warranty-days; `is_active` never cleared; member rows never mutated) · Q2 universal quantifiers **6** · Q3 derived-status-vs-gate **3** · Q4 serializer projections **4** · Q5 list semantics **5** · Q6 cascade legs that don't fire **6** · Q7 version ledger **7** · Q8 unenforced uniqueness/scope **7** · Q9 error precedence **6** · Q10 timestamps **5**.

**Orchestrator verification:** `wc -l` 595 == 595; `diff` of all `^#` headings PRD vs PRD_COMPLETED empty (no sections added); `find implementation test_suite test_helpers -newer results.1.json` empty — Step 9 touched no code or test file, so the 8 green rounds still describe the shipped tree.

## Pipeline complete — 2026-08-08T20:40:00.000Z

112/112 tests passing on 16/16 sweep rounds. 0 deletions, 0 fixes. Step 8 skipped; Step 9 produced 55 edits (33 pins + 22 mismatches).
