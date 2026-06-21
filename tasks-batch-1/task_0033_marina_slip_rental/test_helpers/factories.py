"""Payload factories — one per writeable entity (PRD §3-declared input fields only)."""

_email_counter = [0]


def _next_email() -> str:
    _email_counter[0] += 1
    return f"tenant{_email_counter[0]}@example.com"


_harbor_code_counter = [0]
_HARBOR_CODE_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _next_harbor_code() -> str:
    """3-uppercase-letter harbor code, unique within a single test run."""
    n = _harbor_code_counter[0]
    _harbor_code_counter[0] += 1
    a = _HARBOR_CODE_LETTERS[n // (26 * 26) % 26]
    b = _HARBOR_CODE_LETTERS[n // 26 % 26]
    c = _HARBOR_CODE_LETTERS[n % 26]
    return f"{a}{b}{c}"


# ─── Marina (PRD §3.1) ──────────────────────────────────────────


def create_marina_payload(
    name: str = "Test Marina",
    harbor_code: str = None,
    liveaboard_cap: int = 3,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "harbor_code": harbor_code if harbor_code is not None else _next_harbor_code(),
        "liveaboard_cap": liveaboard_cap,
    }
    payload.update(overrides)
    return payload


# ─── Slip (PRD §3.1) ────────────────────────────────────────────


def create_slip_payload(
    slip_number: str = "A-1",
    length_ft: float = 50,
    beam_ft: float = 15,
    power_amp: str = "A50",
    base_daily_rate_cents: int = 5000,
    **overrides,
) -> dict:
    payload = {
        "slip_number": slip_number,
        "length_ft": length_ft,
        "beam_ft": beam_ft,
        "power_amp": power_amp,
        "base_daily_rate_cents": base_daily_rate_cents,
    }
    payload.update(overrides)
    return payload


# ─── Tenant (PRD §3.2) ──────────────────────────────────────────


def create_tenant_payload(
    email: str = None,
    full_name: str = "Test Tenant",
    **overrides,
) -> dict:
    payload = {
        "email": email if email is not None else _next_email(),
        "full_name": full_name,
    }
    payload.update(overrides)
    return payload


# ─── Vessel (PRD §3.2) ──────────────────────────────────────────


def create_vessel_payload(
    tenant_id: str,
    name: str = "Test Vessel",
    loa_ft: float = 40,
    beam_ft: float = 12,
    insurance_policy_number: str = "POL-001",
    insurance_expires_on: str = "2027-01-01",
    insurance_coverage_cents: int = 6_000_000,
    **overrides,
) -> dict:
    payload = {
        "tenant_id": tenant_id,
        "name": name,
        "loa_ft": loa_ft,
        "beam_ft": beam_ft,
        "insurance_policy_number": insurance_policy_number,
        "insurance_expires_on": insurance_expires_on,
        "insurance_coverage_cents": insurance_coverage_cents,
    }
    payload.update(overrides)
    return payload


# ─── Liveaboard application / approval (PRD §3.3) ───────────────


def liveaboard_application_payload(marina_id: str, **overrides) -> dict:
    payload = {"marina_id": marina_id}
    payload.update(overrides)
    return payload


def liveaboard_approve_payload(marina_id: str, **overrides) -> dict:
    payload = {"marina_id": marina_id}
    payload.update(overrides)
    return payload


def liveaboard_revoke_payload(marina_id: str, **overrides) -> dict:
    payload = {"marina_id": marina_id}
    payload.update(overrides)
    return payload


# ─── Lease (PRD §3.4) ───────────────────────────────────────────


def create_lease_payload(
    marina_id: str,
    slip_id: str,
    tenant_id: str,
    vessel_id: str,
    start_date: str,
    end_date: str,
    expected_slip_version: int,
    is_liveaboard: bool = False,
    **overrides,
) -> dict:
    payload = {
        "marina_id": marina_id,
        "slip_id": slip_id,
        "tenant_id": tenant_id,
        "vessel_id": vessel_id,
        "start_date": start_date,
        "end_date": end_date,
        "is_liveaboard": is_liveaboard,
        "expected_slip_version": expected_slip_version,
    }
    payload.update(overrides)
    return payload


# ─── Pump-out (PRD §3.6) ────────────────────────────────────────


def create_pump_out_request_payload(lease_id: str, **overrides) -> dict:
    payload = {"lease_id": lease_id}
    payload.update(overrides)
    return payload


# ─── Tow-assist (PRD §3.7) ──────────────────────────────────────


def create_tow_assist_event_payload(
    tenant_id: str,
    vessel_id: str,
    marina_id: str,
    incident_distance_nm: float,
    **overrides,
) -> dict:
    payload = {
        "tenant_id": tenant_id,
        "vessel_id": vessel_id,
        "marina_id": marina_id,
        "incident_distance_nm": incident_distance_nm,
    }
    payload.update(overrides)
    return payload


# ─── Transfer waitlist (PRD §3.9) ───────────────────────────────


def create_transfer_waitlist_payload(
    marina_id: str,
    tenant_id: str,
    from_lease_id: str,
    target_slip_id: str,
    **overrides,
) -> dict:
    payload = {
        "marina_id": marina_id,
        "tenant_id": tenant_id,
        "from_lease_id": from_lease_id,
        "target_slip_id": target_slip_id,
    }
    payload.update(overrides)
    return payload


# ─── Clock (PRD §2.10) ──────────────────────────────────────────


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
