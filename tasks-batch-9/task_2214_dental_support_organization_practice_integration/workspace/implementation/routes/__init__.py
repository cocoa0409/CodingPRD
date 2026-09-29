"""Route blueprints, one module per resource group."""

from routes import (
    affiliations,
    agreements,
    batches,
    clock_control,
    consolidations,
    conversion_vendors,
    doctors,
    earnout,
    employments,
    payer_contracts,
    payer_enrollments,
    practices,
    quality,
    supply,
)

BLUEPRINTS = (
    affiliations.bp,
    conversion_vendors.bp,
    practices.bp,
    doctors.bp,
    employments.bp,
    agreements.bp,
    batches.bp,
    payer_contracts.bp,
    payer_enrollments.bp,
    earnout.bp,
    supply.bp,
    consolidations.bp,
    quality.bp,
    clock_control.bp,
)
