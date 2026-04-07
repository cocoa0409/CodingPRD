import { getCustomer, getInvoice, listInvoices } from './resources';
import { DEFAULT_ROLE, Role } from './constants';

export interface ConservationLawResult {
  law: string;
  passed: boolean;
  details?: string;
  expected?: any;
  actual?: any;
}

export interface ConservationLawOptions {
  customerIds: string[];
  role?: Role;

  failFast?: boolean;
}

function asInt(n: any): number | null {
  return typeof n === 'number' && Number.isFinite(n) ? Math.trunc(n) : null;
}

export async function assertConservationLaws(
  workspaceId: string,
  options: ConservationLawOptions
): Promise<ConservationLawResult[]> {
  const role = options.role ?? DEFAULT_ROLE;
  const failFast = options.failFast ?? true;
  const results: ConservationLawResult[] = [];

  function check(law: string, passed: boolean, details?: string, expected?: any, actual?: any) {
    const result: ConservationLawResult = { law, passed, details, expected, actual };
    results.push(result);
    if (!passed && failFast) {
      throw new Error(
        `Conservation law violated: ${law}\n` +
          (details ? `  Details: ${details}\n` : '') +
          `  Expected: ${JSON.stringify(expected)}\n` +
          `  Actual: ${JSON.stringify(actual)}`
      );
    }
  }

  for (const customerId of options.customerIds) {
    const cust = await getCustomer(workspaceId, customerId, role);

    const custBalanceDue = asInt(cust?.balance_due_cents);
    const custUnappliedCash = asInt(cust?.unapplied_cash_cents);
    const custAvailableCredit = asInt(cust?.available_credit_cents);

    check(
      `Customer ${customerId}: balance_due_cents is a finite number`,
      custBalanceDue !== null,
      'Customer must expose balance_due_cents as a finite number',
      'finite number',
      cust?.balance_due_cents
    );
    check(
      `Customer ${customerId}: unapplied_cash_cents is a finite number`,
      custUnappliedCash !== null,
      'Customer must expose unapplied_cash_cents as a finite number',
      'finite number',
      cust?.unapplied_cash_cents
    );
    check(
      `Customer ${customerId}: available_credit_cents is a finite number`,
      custAvailableCredit !== null,
      'Customer must expose available_credit_cents as a finite number',
      'finite number',
      cust?.available_credit_cents
    );

    if (custBalanceDue !== null) {
      check(
        `Customer ${customerId}: balance_due_cents >= 0`,
        custBalanceDue >= 0,
        'Customer balance_due_cents must not be negative',
        '>= 0',
        custBalanceDue
      );
    }
    if (custUnappliedCash !== null) {
      check(
        `Customer ${customerId}: unapplied_cash_cents >= 0`,
        custUnappliedCash >= 0,
        'Customer unapplied_cash_cents must not be negative',
        '>= 0',
        custUnappliedCash
      );
    }
    if (custAvailableCredit !== null) {
      check(
        `Customer ${customerId}: available_credit_cents >= 0`,
        custAvailableCredit >= 0,
        'Customer available_credit_cents must not be negative',
        '>= 0',
        custAvailableCredit
      );
    }

    const invoiceSummaries = await listInvoices(workspaceId, { customer_id: customerId }, role);

    let sumExposureDue = 0;
    for (const summary of invoiceSummaries) {
      const invId = (summary?.invoice_id ?? summary?.id) as string | undefined;

      check(
        `Invoice list item: invoice_id is present`,
        typeof invId === 'string' && invId.length > 0,
        'listInvoices items must include invoice_id (or id) so invariants can be checked',
        'non-empty string',
        invId
      );
      if (!invId) continue;

      const inv = await getInvoice(workspaceId, invId, role);
      const invStatus = inv?.status as string | undefined;
      const amountDue = asInt(inv?.amount_due_cents);
      const amountDisputed = asInt(inv?.amount_disputed_cents);

      check(
        `Invoice ${invId}: amount_due_cents is a finite number`,
        amountDue !== null,
        'Invoice must expose amount_due_cents as a finite number',
        'finite number',
        inv?.amount_due_cents
      );
      check(
        `Invoice ${invId}: amount_disputed_cents is a finite number`,
        amountDisputed !== null,
        'Invoice must expose amount_disputed_cents as a finite number',
        'finite number',
        inv?.amount_disputed_cents
      );

      if (amountDue !== null) {
        check(
          `Invoice ${invId}: amount_due_cents >= 0`,
          amountDue >= 0,
          'Invoice amount_due_cents must not be negative',
          '>= 0',
          amountDue
        );
      }
      if (amountDisputed !== null) {
        check(
          `Invoice ${invId}: amount_disputed_cents >= 0`,
          amountDisputed >= 0,
          'Invoice amount_disputed_cents must not be negative',
          '>= 0',
          amountDisputed
        );
      }
      if (amountDue !== null && amountDisputed !== null) {
        check(
          `Invoice ${invId}: amount_disputed_cents <= amount_due_cents`,
          amountDisputed <= amountDue,
          'Disputed amounts cannot exceed amount due on the invoice',
          `<= ${amountDue}`,
          amountDisputed
        );
      }

      if (invStatus === 'CLOSED' && amountDue !== null) {
        check(
          `Invoice ${invId}: CLOSED implies amount_due_cents == 0`,
          amountDue === 0,
          'A CLOSED invoice must be fully settled and have amount_due_cents == 0',
          0,
          amountDue
        );
      }

      if (invStatus !== 'DRAFT' && invStatus !== 'VOIDED' && amountDue !== null) {
        sumExposureDue += amountDue;
      }
    }

    if (custBalanceDue !== null) {
      check(
        `Customer ${customerId}: balance_due_cents = Σ invoice.amount_due_cents (excluding DRAFT/VOIDED)`,
        custBalanceDue === sumExposureDue,
        'Customer balance_due_cents should equal sum of non-DRAFT, non-VOIDED invoice amount_due_cents',
        sumExposureDue,
        custBalanceDue
      );
    }

    if (cust?.status === 'CLOSED') {
      check(
        `Customer ${customerId}: CLOSED implies balance_due/unapplied_cash/available_credit are all 0`,
        (custBalanceDue ?? -1) === 0 && (custUnappliedCash ?? -1) === 0 && (custAvailableCredit ?? -1) === 0,
        'Closed customers must have no open invoice balance, no unapplied cash, and no available credits',
        { balance_due_cents: 0, unapplied_cash_cents: 0, available_credit_cents: 0 },
        {
          balance_due_cents: cust?.balance_due_cents,
          unapplied_cash_cents: cust?.unapplied_cash_cents,
          available_credit_cents: cust?.available_credit_cents
        }
      );
    }
  }

  return results;
}
