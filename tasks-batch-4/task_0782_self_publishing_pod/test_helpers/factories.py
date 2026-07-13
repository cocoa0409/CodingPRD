"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_publisher_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {"name": f"Indie House {n}", "email": f"pub{n}@x.com"}
    defaults.update(overrides)
    return defaults


def create_title_payload(publisher_id, **overrides) -> dict:
    n = _uniq()
    defaults = {
        "publisher_id": publisher_id,
        "title": f"Book {n}",
        "language": "en",
        "bisac_category": "FIC000000",
    }
    defaults.update(overrides)
    return defaults


def create_print_format_payload(**overrides) -> dict:
    defaults = {
        "format_type": "PRINT",
        "trim_size": "6x9",
        "interior_color": "BW",
        "page_count": 200,
    }
    defaults.update(overrides)
    return defaults


def create_ebook_format_payload(**overrides) -> dict:
    defaults = {"format_type": "EBOOK", "file_size_mb": 2.0}
    defaults.update(overrides)
    return defaults


def create_interior_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_type": "INTERIOR",
        "file_ref": "s3://int.pdf",
        "file_format": "PDF",
        "declared_page_count": 200,
    }
    defaults.update(overrides)
    return defaults


def create_cover_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_type": "COVER",
        "file_ref": "s3://cov.jpg",
        "file_format": "JPG",
        "paper_type": "WHITE",
        "declared_spine_mm": 11.44,
    }
    defaults.update(overrides)
    return defaults


def create_isbn_payload(isbn_13, **overrides) -> dict:
    defaults = {"isbn_13": isbn_13}
    defaults.update(overrides)
    return defaults


def create_channel_payload(**overrides) -> dict:
    from .constants import AMZ_CHANNEL
    defaults = dict(AMZ_CHANNEL)
    defaults.update(overrides)
    return defaults


def create_price_payload(expected_format_version, channel_id, list_price_cents,
                         territory="US", effective_from="2026-01-01T00:00:00Z",
                         **overrides) -> dict:
    defaults = {
        "expected_format_version": expected_format_version,
        "channel_id": channel_id,
        "territory": territory,
        "list_price_cents": list_price_cents,
        "effective_from": effective_from,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_request_payload(channel_id, territory="US", **overrides) -> dict:
    defaults = {"channel_id": channel_id, "territory": territory}
    defaults.update(overrides)
    return defaults


def create_sales_line_payload(format_id, channel_id, units, line_type, sale_date,
                              territory="US", **overrides) -> dict:
    defaults = {
        "format_id": format_id,
        "channel_id": channel_id,
        "territory": territory,
        "units": units,
        "line_type": line_type,
        "sale_date": sale_date,
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(period_start, period_end, **overrides) -> dict:
    defaults = {"period_start": period_start, "period_end": period_end}
    defaults.update(overrides)
    return defaults
